"""Message claims and complete HTTP replay; uncertain writes are never restarted."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

import aiomysql
import pymysql

from app.nodes.persist import _parse_mysql_uri
from app.storage.mysql import MESSAGE_LOG, SESSION_INIT

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


class IdempotencyStore(Protocol):
    async def begin(
        self, message_id: str, *, conversation_id: str, user_id: str, room_id: str, raw_text: str,
    ) -> IdempotencyRecord | None: ...

    async def complete(
        self, message_id: str, *, reply_text: str | None, product_type: str | None,
        intent: str | None, api_code: int | None, api_result: Any, error: str | None,
        latency_ms: int, response: dict[str, Any] | None = None, http_status: int = 200,
    ) -> None: ...


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
            started_at=self._clock(),
        )
        return None

    async def complete(
        self, message_id: str, *, reply_text: str | None, product_type: str | None,
        intent: str | None, api_code: int | None, api_result: Any, error: str | None,
        latency_ms: int, response: dict[str, Any] | None = None, http_status: int = 200,
    ) -> None:
        self._rows[message_id] = replace(
            self._rows[message_id], status="done", reply_text=reply_text, api_code=api_code,
            response=response, http_status=http_status, error=error,
        )


class MySQLIdempotencyStore:
    """Persist a claim before execution and a complete HTTP snapshot afterwards."""

    def __init__(
        self, business_mysql_uri: str, *, timeout_seconds: float = 5.0,
        processing_timeout_seconds: float = 120.0,
    ) -> None:
        self._conn_args = _parse_mysql_uri(business_mysql_uri)
        self._timeout = timeout_seconds
        self._processing_timeout = processing_timeout_seconds

    async def _connect(self) -> aiomysql.Connection:
        host, port, user, password, db = self._conn_args
        return await asyncio.wait_for(
            aiomysql.connect(host=host, port=port, user=user, password=password, db=db,
                             charset="utf8mb4", init_command=SESSION_INIT, autocommit=True),
            timeout=self._timeout,
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
                    message_id=message_id, status="done" if row[0] is not None else "in_progress",
                    reply_text=row[0], api_code=row[1], response=response,
                    http_status=row[3] or 200, error=row[4], user_id=row[5], room_id=row[6],
                    started_at=float(row[7]),
                )
                return _existing(record, user_id, room_id, time.time(), self._processing_timeout)
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
