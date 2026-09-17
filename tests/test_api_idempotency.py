"""请求级幂等（ADR 0024 D4，评估 R2）：Java 超时重试 / 企微重投 / 运维重放同一条消息时，
不得重跑整图（确认节点直调后端写接口 → 重复下单 / 重复平仓）。以企微 message_id 去重：
已完成 → 回放上次回复；处理中 → 固定文案；无 message_id → 不做幂等。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.idempotency import (
    IdempotencyRecord,
    InMemoryIdempotencyStore,
    MySQLIdempotencyStore,
)
from app.graph.state import TraceEntry
from app.main import app


class _CountingGraph:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, state: dict, config: dict, **kwargs: object) -> dict:
        self.calls += 1
        return {**state, "product_type": "swap", "intent": "confirm_order",
                "reply_text": f"回复#{self.calls}", "api_code": 0, "api_result": "ok",
                "trace": [TraceEntry(node="ingest")]}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.app.state.main_graph = _CountingGraph()
        c.app.state.idempotency_store = InMemoryIdempotencyStore()
        yield c
        c.app.state.idempotency_store = None


def _body(message_id: int | None, text: str = "确认下单") -> dict:
    inputs = {"rawContent": text, "conversationId": "conv-1", "roomId": "r", "userId": "u"}
    if message_id is not None:
        inputs["messageId"] = message_id
    return {"inputs": inputs, "user": "u"}


def test_duplicate_message_replays_reply_without_rerunning_graph(client: TestClient) -> None:
    first = client.post("/v1/workflows/run", json=_body(7)).json()
    second = client.post("/v1/workflows/run", json=_body(7)).json()
    assert client.app.state.main_graph.calls == 1
    assert second["answer"] == first["answer"] == "回复#1"
    assert second["data"]["outputs"]["replayed"] is True
    assert "replayed" not in first["data"]["outputs"]


def test_in_progress_duplicate_returns_processing_notice(client: TestClient) -> None:
    import asyncio

    store: InMemoryIdempotencyStore = client.app.state.idempotency_store
    asyncio.run(store.begin("9", conversation_id="conv-1", user_id="u", room_id="r", raw_text="x"))
    r = client.post("/v1/workflows/run", json=_body(9)).json()
    assert client.app.state.main_graph.calls == 0
    assert "正在处理" in r["answer"]
    assert r["data"]["outputs"]["replayed"] is True


def test_missing_message_id_is_not_deduplicated(client: TestClient) -> None:
    client.post("/v1/workflows/run", json=_body(None))
    client.post("/v1/workflows/run", json=_body(None))
    assert client.app.state.main_graph.calls == 2


@pytest.mark.asyncio
async def test_inmemory_store_semantics() -> None:
    store = InMemoryIdempotencyStore()
    assert await store.begin("1", conversation_id="c", user_id="u", room_id="r", raw_text="x") is None
    rec = await store.begin("1", conversation_id="c", user_id="u", room_id="r", raw_text="x")
    assert isinstance(rec, IdempotencyRecord) and rec.status == "in_progress"
    await store.complete("1", reply_text="done", product_type="swap", intent="confirm_order",
                         api_code=0, api_result="ok", error=None, latency_ms=12)
    rec = await store.begin("1", conversation_id="c", user_id="u", room_id="r", raw_text="x")
    assert rec is not None and rec.status == "done" and rec.reply_text == "done"


@pytest.mark.asyncio
async def test_mysql_store_duplicate_key_reads_existing_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """INSERT 撞 uk_message_id → 读已有行；不依赖真实 MySQL，mock aiomysql。"""
    from contextlib import asynccontextmanager

    import pymysql

    cur = MagicMock()
    cur.execute = AsyncMock(side_effect=[pymysql.err.IntegrityError(1062, "dup"), None])
    cur.fetchone = AsyncMock(return_value=("上次回复", 0))

    @asynccontextmanager
    async def _cursor():  # type: ignore[no-untyped-def]
        yield cur

    conn = MagicMock()
    conn.cursor = _cursor
    conn.close = MagicMock()
    monkeypatch.setattr("app.api.idempotency.aiomysql.connect", AsyncMock(return_value=conn))

    store = MySQLIdempotencyStore("mysql+aiomysql://u:p@h:3306/biz")
    rec = await store.begin("77", conversation_id="c", user_id="u", room_id="r", raw_text="x")
    assert rec is not None and rec.status == "done" and rec.reply_text == "上次回复"
    assert "INSERT INTO message_log" in cur.execute.call_args_list[0].args[0]
    assert "SELECT" in cur.execute.call_args_list[1].args[0]
