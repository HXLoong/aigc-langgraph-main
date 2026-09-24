"""Operator-only reconciliation from original Java HTTP receipts, without trade writes.

Java's access log does not enable response_body for operate endpoints by default.
Missing receipts therefore remain unknown; neither an order row nor an absent log
proves that a timed-out request did (or did not) execute.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import aiomysql

from app.storage.idempotency import IdempotencyRecord, IdempotencyStore
from app.storage.mysql import connection_args

_ENDPOINTS = ("/admin-api/swap-order/operate", "/admin-api/financial-orders/operate")
_MAX_RECEIPTS = 100


@dataclass(frozen=True, slots=True)
class JavaAuditEntry:
    log_id: int
    endpoint: str
    request_params: str
    response_body: str | None
    result_code: int | None
    started_at: float
    finished_at: float | None


class ReceiptReader(Protocol):
    async def read(self, record: IdempotencyRecord) -> list[JavaAuditEntry]: ...


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    outcome: Literal["response_found", "unknown", "changed", "already_done", "in_progress", "missing"]
    reason: str
    applied: bool = False
    source: str | None = None
    source_id: int | None = None


class JavaAuditReader:
    """Read the shared Java database; this class executes SELECT statements only."""

    def __init__(self, mysql_uri: str, *, timeout_seconds: float = 5.0) -> None:
        self._kwargs = connection_args(mysql_uri)
        self._timeout = timeout_seconds

    async def read(self, record: IdempotencyRecord) -> list[JavaAuditEntry]:
        # Never use the legacy last-18-digit normalization to associate receipts.
        if not record.message_id.isascii() or not record.message_id.isdecimal():
            return []
        async with asyncio.timeout(self._timeout):
            conn = await aiomysql.connect(**self._kwargs, autocommit=True)
            try:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id, request_url, request_params, response_body, result_code, "
                        "UNIX_TIMESTAMP(begin_time), UNIX_TIMESTAMP(end_time) "
                        "FROM infra_api_access_log WHERE deleted=0 AND request_method='POST' "
                        "AND request_url IN (%s, %s) AND begin_time >= FROM_UNIXTIME(%s) "
                        "AND request_params LIKE %s ORDER BY id LIMIT %s",
                        (*_ENDPOINTS, record.started_at, f"%{record.message_id}%", _MAX_RECEIPTS + 1),
                    )
                    rows = await cur.fetchall()
                return [JavaAuditEntry(
                    log_id=int(row[0]), endpoint=row[1], request_params=row[2] or "",
                    response_body=row[3], result_code=row[4], started_at=float(row[5]),
                    finished_at=float(row[6]) if row[6] is not None else None,
                ) for row in rows]
            finally:
                conn.close()


def _object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) else None


def _matching_request(entry: JavaAuditEntry, record: IdempotencyRecord) -> dict[str, Any] | None:
    params = _object(entry.request_params)
    body = _object(params.get("body")) if params is not None else None
    if body is None or entry.endpoint not in _ENDPOINTS or entry.started_at < record.started_at:
        return None
    for field, expected in (
        ("messageId", record.message_id), ("userId", record.user_id),
        ("roomId", record.room_id), ("conversationId", record.conversation_id),
        ("rawContent", record.raw_text),
    ):
        actual = body.get(field)
        if field == "messageId" and isinstance(actual, int) and not isinstance(actual, bool):
            actual = str(actual)
        if actual != expected:
            return None
    return body


def _response(
    record: IdempotencyRecord, entry: JavaAuditEntry, request_body: dict[str, Any],
    receipt: dict[str, Any], reply: str,
) -> dict[str, Any]:
    # Construct only the transport envelope. Business text is the original Java text.
    # New envelope identifiers distinguish recovery from an unavailable original HTTP snapshot.
    workflow_id, task_id, message_id = (str(uuid.uuid4()) for _ in range(3))
    now = int(time.time())
    code = receipt["code"]
    return {
        "workflow_run_id": workflow_id, "task_id": task_id, "id": message_id,
        "message_id": message_id, "conversationId": record.conversation_id,
        "conversation_id": record.conversation_id, "answer": reply,
        "event": "message", "mode": "advanced-chat", "created_at": int(record.started_at),
        "metadata": {"reconstructed_envelope": True},
        "data": {
            "id": workflow_id, "workflow_id": "otc-agent-langgraph",
            "status": "succeeded" if code == 0 else "failed",
            "error": None if code == 0 else "后端已返回业务错误，请查看原始回复。",
            "created_at": int(record.started_at), "finished_at": now,
            "outputs": {
                "reply_text": reply, "api_code": code, "api_result": reply,
                "intent": request_body.get("type"),
                "idempotency_status": "done",
                "reconciliation": {
                    "source": "java_api_access_log", "source_id": entry.log_id,
                    "endpoint": entry.endpoint, "completed_at": entry.finished_at,
                    "meaning": "original_backend_response", "reconciled_at": now,
                },
            },
        },
    }


async def reconcile_request(
    store: IdempotencyStore, reader: ReceiptReader, message_id: str, *, user_id: str,
    room_id: str, apply: bool = False,
) -> ReconciliationResult:
    """Inspect first; mutate only the unchanged uncertain claim when explicitly applied."""
    record = await store.get(message_id, user_id=user_id, room_id=room_id)
    if record is None:
        return ReconciliationResult("missing", "no_langgraph_claim")
    if record.status == "done":
        return ReconciliationResult("already_done", "preserve_completed_snapshot")
    if record.status == "in_progress":
        return ReconciliationResult("in_progress", "request_not_expired")
    entries = await reader.read(record)
    if len(entries) > _MAX_RECEIPTS:
        return ReconciliationResult("unknown", "receipt_search_limit_exceeded")
    matches = [(entry, body) for entry in entries
               if (body := _matching_request(entry, record)) is not None]
    if not matches:
        return ReconciliationResult("unknown", "no_matching_receipt_not_proof_of_no_write")
    if len(matches) != 1:
        return ReconciliationResult("unknown", "multiple_backend_calls_require_manual_review")
    entry, body = matches[0]
    receipt = _object(entry.response_body)
    if receipt is None or entry.finished_at is None:
        return ReconciliationResult("unknown", "original_response_unavailable",
                                    source="java_api_access_log", source_id=entry.log_id)
    code = receipt.get("code")
    reply = receipt.get("data") if code == 0 else receipt.get("msg")
    if (
        not isinstance(code, int) or isinstance(code, bool) or code != entry.result_code
        or not isinstance(reply, str) or not reply.strip()
    ):
        return ReconciliationResult("unknown", "original_response_incomplete",
                                    source="java_api_access_log", source_id=entry.log_id)
    if apply:
        recovered = await store.reconcile(
            record, response=_response(record, entry, body, receipt, reply), reply_text=reply,
            api_code=code, api_result=reply,
        )
        if not recovered:
            return ReconciliationResult("changed", "claim_changed_during_reconciliation")
    return ReconciliationResult("response_found", "original_response_verified", applied=apply,
                                source="java_api_access_log", source_id=entry.log_id)
