"""Reconciliation must recover evidence without ever invoking a trade operation."""
from __future__ import annotations

import importlib.util
import json
from dataclasses import replace

import pytest

from app.storage.idempotency import IdempotencyConflictError, InMemoryIdempotencyStore


def test_independent_reconciliation_is_available() -> None:
    assert importlib.util.find_spec("app.storage.reconciliation") is not None


async def test_timeout_snapshot_remains_uncertain() -> None:
    store = InMemoryIdempotencyStore()
    await store.begin("123", conversation_id="c", user_id="u", room_id="r", raw_text="确认")
    await store.complete(
        "123", reply_text="", product_type="swap", intent="confirm_order", api_code=None,
        api_result=None, error="workflow_timeout", latency_ms=60_000,
        response={"code": "workflow_timeout", "status": 504}, http_status=504,
    )
    record = await store.begin(
        "123", conversation_id="c", user_id="u", room_id="r", raw_text="确认",
    )
    assert record is not None and record.status == "uncertain"


async def _claim():
    from app.storage.idempotency import IdempotencyRecord

    store = InMemoryIdempotencyStore(processing_timeout_seconds=10, clock=lambda: 100.0)
    await store.begin("123", conversation_id="c", user_id="u", room_id="r", raw_text="确认")
    record = await store.get("123", user_id="u", room_id="r")
    assert isinstance(record, IdempotencyRecord)
    store._clock = lambda: 200.0
    return store, replace(record, status="uncertain")


def _audit(response: str | None, *, user: str = "u", log_id: int = 7):
    from app.storage.reconciliation import JavaAuditEntry

    return JavaAuditEntry(
        log_id=log_id, endpoint="/admin-api/swap-order/operate",
        request_params=json.dumps({"body": json.dumps({
            "messageId": 123, "userId": user, "roomId": "r", "conversationId": "c",
            "rawContent": "确认", "type": "confirm_order",
        })}), response_body=response, result_code=0, started_at=101.0, finished_at=108.0,
    )


async def test_only_exact_original_response_can_recover_and_apply_is_explicit() -> None:
    from app.storage.reconciliation import reconcile_request

    store, _ = await _claim()

    class Reader:
        async def read(self, record):
            return [_audit(json.dumps({"code": 0, "data": "后端原文：已登记", "msg": ""}))]

    dry = await reconcile_request(store, Reader(), "123", user_id="u", room_id="r")
    assert dry.outcome == "response_found" and not dry.applied
    assert (await store.get("123", user_id="u", room_id="r")).status == "uncertain"
    applied = await reconcile_request(
        store, Reader(), "123", user_id="u", room_id="r", apply=True,
    )
    assert applied.applied
    replay = await store.get("123", user_id="u", room_id="r")
    assert replay.status == "done" and replay.response["answer"] == "后端原文：已登记"
    assert replay.response["data"]["outputs"]["reconciliation"]["source_id"] == 7


@pytest.mark.parametrize("kind", ["missing", "different_user", "multiple", "malformed"])
async def test_incomplete_or_ambiguous_evidence_stays_reserved(kind: str) -> None:
    from app.storage.reconciliation import reconcile_request

    store, _ = await _claim()
    response = json.dumps({"code": 0, "data": "真实回复"})
    entries = {
        "missing": [_audit(None)],
        "different_user": [_audit(response, user="other")],
        "multiple": [_audit(response), _audit(response, log_id=8)],
        "malformed": [_audit('{"code":0')],
    }[kind]

    class Reader:
        async def read(self, record):
            return entries

    result = await reconcile_request(store, Reader(), "123", user_id="u", room_id="r", apply=True)
    assert result.outcome == "unknown" and not result.applied
    assert (await store.get("123", user_id="u", room_id="r")).status == "uncertain"


async def test_recovery_checks_owner_and_cannot_overwrite_new_completion() -> None:
    from app.storage.reconciliation import reconcile_request

    store, _ = await _claim()

    class Reader:
        async def read(self, record):
            await store.complete(
                "123", reply_text="原请求已正常结束", product_type="swap", intent="confirm_order",
                api_code=0, api_result="原请求已正常结束", error=None, latency_ms=1,
                response={"answer": "原请求已正常结束"},
            )
            return [_audit(json.dumps({"code": 0, "data": "更早的结果"}))]

    with pytest.raises(IdempotencyConflictError):
        await reconcile_request(store, Reader(), "123", user_id="wrong", room_id="r", apply=True)
    result = await reconcile_request(store, Reader(), "123", user_id="u", room_id="r", apply=True)
    assert result.outcome == "changed" and not result.applied
    assert (await store.get("123", user_id="u", room_id="r")).reply_text == "原请求已正常结束"


@pytest.mark.parametrize("completed", [False, True])
async def test_mysql_recovery_locks_and_rechecks_claim_before_commit(monkeypatch, completed) -> None:
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from app.storage.idempotency import MySQLIdempotencyStore

    _, expected = await _claim()
    cursor = MagicMock(execute=AsyncMock(), fetchone=AsyncMock(return_value=(
        "已完成" if completed else None, None, None, 200, None, "u", "r", 100, "c", "确认",
    )))

    @asynccontextmanager
    async def context():
        yield cursor

    conn = MagicMock(begin=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock(), cursor=context)
    store = MySQLIdempotencyStore("mysql+aiomysql://u:p@localhost/shared")
    monkeypatch.setattr(store, "_connect", AsyncMock(return_value=conn))
    result = await store.reconcile(
        expected, response={"answer": "后端原文"}, reply_text="后端原文", api_code=0,
        api_result="后端原文",
    )
    assert result is not completed
    assert cursor.execute.await_args_list[0].args[0].endswith("FOR UPDATE")
    writes = [call for call in cursor.execute.await_args_list if call.args[0].startswith("UPDATE")]
    assert len(writes) == (0 if completed else 1)
    assert conn.commit.await_count == (0 if completed else 1)
    assert conn.rollback.await_count == (1 if completed else 0)
