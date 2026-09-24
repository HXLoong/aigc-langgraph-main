"""Message claims and complete HTTP replay; uncertain writes are never restarted."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

import aiomysql
import pymysql

from app.storage.mysql import MESSAGE_LOG, connection_args

PROCESSING_NOTICE = "该消息正在处理中，请勿重复提交。"
UNCERTAIN_NOTICE = "该消息的执行结果待核对，请勿重复提交。"


class IdempotencyConflictError(ValueError):
    """The message identity belongs to another user or room."""


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    message_id: str
    status: Literal["in_progress", "done", "uncertain"]
    reply_text: str | None = None
    api_code: int | None = None
    response: dict[str, Any] | None = None
    http_status: int = 200
    error: str | None = None
    user_id: str = ""
    room_id: str = ""
    started_at: float = 0.0
    conversation_id: str = ""
    raw_text: str = ""


class IdempotencyStore(Protocol):
    async def begin(
        self, message_id: str, *, conversation_id: str, user_id: str, room_id: str, raw_text: str,
    ) -> IdempotencyRecord | None: ...

    async def complete(
        self, message_id: str, *, reply_text: str | None, product_type: str | None,
        intent: str | None, api_code: int | None, api_result: Any, error: str | None,
        latency_ms: int, response: dict[str, Any] | None = None, http_status: int = 200,
    ) -> None: ...

    async def get(
        self, message_id: str, *, user_id: str, room_id: str,
    ) -> IdempotencyRecord | None: ...

    async def reconcile(
        self, expected: IdempotencyRecord, *, response: dict[str, Any],
        reply_text: str, api_code: int, api_result: str,
    ) -> bool: ...


def response_is_uncertain(response: dict[str, Any] | None, http_status: int = 200) -> bool:
    """Transport failures retain their claim even when an error HTTP snapshot exists."""
    if http_status == 504:
        return True
    if not response:
        return False
    if response.get("idempotency_status") == "uncertain":
        return True
    data = response.get("data")
    outputs = data.get("outputs") if isinstance(data, dict) else None
    if not isinstance(outputs, dict):
        return False
    if outputs.get("idempotency_status") == "uncertain":
        return True
    error = outputs.get("error")
    errors = [error, *(error.get("causes") or [])] if isinstance(error, dict) else []
    return any(isinstance(item, dict) and item.get("type") in {
        "BackendUnreachableError", "WorkflowTimeout", "EmptyBackendResultError",
    } for item in errors)


def _existing(
    record: IdempotencyRecord, user_id: str, room_id: str, now: float, timeout: float,
) -> IdempotencyRecord:
    if (record.user_id, record.room_id) != (user_id, room_id):
        raise IdempotencyConflictError("消息标识与用户或群不匹配")
    if record.status == "in_progress" and now - record.started_at >= timeout:
        return replace(record, status="uncertain")
    return record


class InMemoryIdempotencyStore:
    """Single-process test/development store with the MySQL replay semantics."""

    def __init__(
        self, *, processing_timeout_seconds: float = 120.0, clock: Callable[[], float] = time.time,
    ) -> None:
        self._rows: dict[str, IdempotencyRecord] = {}
        self._clock = clock
        self._timeout = processing_timeout_seconds

    async def begin(
        self, message_id: str, *, conversation_id: str, user_id: str, room_id: str, raw_text: str,
    ) -> IdempotencyRecord | None:
        record = self._rows.get(message_id)
        if record is not None:
            return _existing(record, user_id, room_id, self._clock(), self._timeout)
        self._rows[message_id] = IdempotencyRecord(
            message_id=message_id, status="in_progress", user_id=user_id, room_id=room_id,
            started_at=self._clock(), conversation_id=conversation_id, raw_text=raw_text,
        )
        return None

    async def complete(
        self, message_id: str, *, reply_text: str | None, product_type: str | None,
        intent: str | None, api_code: int | None, api_result: Any, error: str | None,
        latency_ms: int, response: dict[str, Any] | None = None, http_status: int = 200,
    ) -> None:
        self._rows[message_id] = replace(
            self._rows[message_id],
            status="uncertain" if response_is_uncertain(response, http_status) else "done",
            reply_text=reply_text, api_code=api_code,
            response=deepcopy(response), http_status=http_status, error=error,
        )

    async def get(
        self, message_id: str, *, user_id: str, room_id: str,
    ) -> IdempotencyRecord | None:
        record = self._rows.get(message_id)
        return None if record is None else deepcopy(
            _existing(record, user_id, room_id, self._clock(), self._timeout),
        )

    async def reconcile(
        self, expected: IdempotencyRecord, *, response: dict[str, Any],
        reply_text: str, api_code: int, api_result: str,
    ) -> bool:
        current = self._rows.get(expected.message_id)
        if current is None or expected.status != "uncertain":
            return False
        current = _existing(current, expected.user_id, expected.room_id, self._clock(), self._timeout)
        if current != expected:
            return False
        self._rows[expected.message_id] = replace(
            current, status="done", response=deepcopy(response), reply_text=reply_text,
            api_code=api_code, http_status=200, error=None,
        )
        return True


class MySQLIdempotencyStore:
    """Persist a claim before execution and a complete HTTP snapshot afterwards."""

    def __init__(
        self, mysql_uri: str, *, timeout_seconds: float = 5.0,
        processing_timeout_seconds: float = 120.0,
    ) -> None:
        self._conn_args = connection_args(mysql_uri)
        self._timeout = timeout_seconds
        self._processing_timeout = processing_timeout_seconds

    async def _connect(self) -> aiomysql.Connection:
        return await asyncio.wait_for(
            aiomysql.connect(**self._conn_args, autocommit=True), timeout=self._timeout,
        )

    async def begin(
        self, message_id: str, *, conversation_id: str, user_id: str, room_id: str, raw_text: str,
    ) -> IdempotencyRecord | None:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(
                        f"INSERT INTO {MESSAGE_LOG} (message_id, conversation_id, room_id, user_id, "
                        "raw_content, processed_by) VALUES (%s, %s, %s, %s, %s, %s)",
                        (message_id, conversation_id, room_id, user_id, raw_text, "langgraph"),
                    )
                    return None
                except pymysql.err.IntegrityError as exc:
                    if exc.args[0] != 1062:
                        raise
                await cur.execute(
                    "SELECT reply_text, api_code, response_json, http_status, error, user_id, "
                    f"room_id, UNIX_TIMESTAMP(created_at) FROM {MESSAGE_LOG} WHERE message_id = %s",
                    (message_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    raise RuntimeError("idempotency record missing after duplicate claim")
                response = json.loads(row[2]) if row[2] is not None else None
                if response is not None and not isinstance(response, dict):
                    raise ValueError("invalid stored HTTP response")
                record = IdempotencyRecord(
                    message_id=message_id,
                    status="uncertain" if response_is_uncertain(response, row[3] or 200) else (
                        "done" if row[0] is not None else "in_progress"
                    ),
                    reply_text=row[0], api_code=row[1], response=response,
                    http_status=row[3] or 200, error=row[4], user_id=row[5], room_id=row[6],
                    started_at=float(row[7]),
                )
                return _existing(record, user_id, room_id, time.time(), self._processing_timeout)
        finally:
            conn.close()

    async def _read_record(self, cur: Any, message_id: str, *, lock: bool = False) -> IdempotencyRecord | None:
        await cur.execute(
            "SELECT reply_text, api_code, response_json, http_status, error, user_id, "
            f"room_id, UNIX_TIMESTAMP(created_at), conversation_id, raw_content FROM {MESSAGE_LOG} "
            "WHERE message_id = %s" + (" FOR UPDATE" if lock else ""), (message_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        response = json.loads(row[2]) if isinstance(row[2], str) else row[2]
        if response is not None and not isinstance(response, dict):
            raise ValueError("invalid stored HTTP response")
        return IdempotencyRecord(
            message_id=message_id,
            status="uncertain" if response_is_uncertain(response, row[3]) else (
                "done" if row[0] is not None else "in_progress"
            ), reply_text=row[0], api_code=row[1], response=response, http_status=row[3],
            error=row[4], user_id=row[5], room_id=row[6], started_at=float(row[7]),
            conversation_id=row[8], raw_text=row[9],
        )

    async def get(
        self, message_id: str, *, user_id: str, room_id: str,
    ) -> IdempotencyRecord | None:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                record = await self._read_record(cur, message_id)
                return None if record is None else _existing(
                    record, user_id, room_id, time.time(), self._processing_timeout,
                )
        finally:
            conn.close()

    async def reconcile(
        self, expected: IdempotencyRecord, *, response: dict[str, Any],
        reply_text: str, api_code: int, api_result: str,
    ) -> bool:
        if expected.status != "uncertain":
            return False
        conn = await self._connect()
        try:
            await conn.begin()
            async with conn.cursor() as cur:
                current = await self._read_record(cur, expected.message_id, lock=True)
                if current is not None:
                    current = _existing(
                        current, expected.user_id, expected.room_id, time.time(), self._processing_timeout,
                    )
                if current != expected:
                    await conn.rollback()
                    return False
                await cur.execute(
                    f"UPDATE {MESSAGE_LOG} SET reply_text=%s, api_code=%s, api_result=%s, "
                    "error=NULL, response_json=%s, http_status=200 WHERE message_id=%s "
                    "AND user_id=%s AND room_id=%s",
                    (reply_text, api_code, json.dumps(api_result, ensure_ascii=False),
                     json.dumps(response, ensure_ascii=False), expected.message_id,
                     expected.user_id, expected.room_id),
                )
            await conn.commit()
            return True
        except BaseException:
            await conn.rollback()
            raise
        finally:
            conn.close()

    async def complete(
        self, message_id: str, *, reply_text: str | None, product_type: str | None,
        intent: str | None, api_code: int | None, api_result: Any, error: str | None,
        latency_ms: int, response: dict[str, Any] | None = None, http_status: int = 200,
    ) -> None:
        conn = await self._connect()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"UPDATE {MESSAGE_LOG} SET reply_text = %s, product_type = %s, intent = %s, "
                    "api_code = %s, api_result = %s, error = %s, latency_ms = %s, "
                    "response_json = %s, http_status = %s WHERE message_id = %s",
                    (reply_text if reply_text is not None else "", product_type, intent, api_code,
                     None if api_result is None else json.dumps(api_result, ensure_ascii=False),
                     error, latency_ms, None if response is None else json.dumps(response, ensure_ascii=False),
                     http_status, message_id),
                )
        finally:
            conn.close()
