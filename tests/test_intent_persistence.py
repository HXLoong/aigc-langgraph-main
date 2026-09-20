"""HTTP 入口到消息后端的会话持久化契约。"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

import app.main as app_main
from app.config import get_settings
from app.graph.main import build_main_graph
from app.nodes.intent_route import UnknownIntentOutput
from app.tools.message_client import MessageClientHttpx
from tests.intent_fixtures import intent_reply, mock_ainvoke


@pytest.fixture()
def isolated_workflow(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    settings = get_settings().model_copy(update={
        "environment": "staging",
        "use_mysql_checkpointer": False,
        "enable_langfuse": False,
    })
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    monkeypatch.setenv("ENABLE_LANGFUSE", "false")
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = mock_ainvoke(intent_reply(UnknownIntentOutput, label="unknown"))
    monkeypatch.setattr("app.nodes.intent_route.get_qwen_thinking", lambda: llm)
    write_trace = AsyncMock()
    monkeypatch.setattr("app.nodes.persist._write_to_mysql", write_trace)
    return write_trace


def test_development_http_workflow_does_not_write_messages(
    monkeypatch: pytest.MonkeyPatch, isolated_workflow: AsyncMock,
) -> None:
    settings = app_main.get_settings().model_copy(update={"environment": "development"})
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    factory = MagicMock(side_effect=AssertionError("development must not create a message client"))
    monkeypatch.setattr(app_main, "MessageClientHttpx", factory)
    with TestClient(app_main.app) as client:
        response = client.post("/v1/workflows/run", json={
            "inputs": {"raw_content": "你好", "message_id": 42}, "user": "stable-user",
        })
    assert response.status_code == 200, response.text
    assert response.json()["answer"]
    factory.assert_not_called()
    trace = isolated_workflow.call_args.args[0]
    assert any(entry.node == "persist_intent" and entry.decision == "skipped" for entry in trace)


def test_first_turn_persists_generated_conversation_id_and_followup_reuses_it(
    monkeypatch: pytest.MonkeyPatch, isolated_workflow: AsyncMock,
) -> None:
    saved_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        saved_requests.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": True})

    monkeypatch.setattr(app_main, "MessageClientHttpx", lambda: MessageClientHttpx(
        base_url="https://java.invalid", token="", transport=httpx.MockTransport(handler),
    ))
    with TestClient(app_main.app) as client:
        response = client.post("/v1/workflows/run", json={
            "inputs": {"raw_content": "你好", "conversation_id": "", "message_id": 42},
            "user": "stable-user",
        })

        assert response.status_code == 200, response.text
        assert len(saved_requests) == 1
        generated_id = response.json()["conversationId"]
        assert generated_id and generated_id != "stable-user"
        assert saved_requests[0] == {
            "conversationId": generated_id, "messageId": "42",
            "intent": "unknown_intent", "productType": 0, "orderIds": [],
        }
        assert response.json()["answer"]

        followup = client.post("/v1/workflows/run", json={
            "inputs": {"raw_content": "你好", "conversation_id": generated_id, "message_id": 43},
            "user": "stable-user",
        })
        assert followup.status_code == 200, followup.text
        assert followup.json()["conversationId"] == generated_id
        assert [req["messageId"] for req in saved_requests] == ["42", "43"]
        assert saved_requests[1]["conversationId"] == generated_id

    persisted_trace = isolated_workflow.call_args.args[0]
    nodes = [entry.node for entry in persisted_trace]
    assert nodes.index("persist_intent") < nodes.index("render") < nodes.index("record_history")


@pytest.mark.parametrize("status_code,code", [(503, 0), (401, 0), (422, 0), (200, 123)])
def test_set_intent_failure_returns_502_and_persists_failure_trace(
    monkeypatch: pytest.MonkeyPatch, isolated_workflow: AsyncMock,
    status_code: int, code: int,
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(
        status_code, json={"code": code, "msg": "secret-token private-backend-response"},
    ))
    monkeypatch.setattr(app_main, "MessageClientHttpx", lambda: MessageClientHttpx(
        base_url="https://private-backend.invalid", token="secret-token", transport=transport,
    ))
    with TestClient(app_main.app) as client:
        response = client.post("/v1/workflows/run", json={
            "inputs": {"raw_content": "你好", "conversation_id": "", "message_id": 42},
            "user": "stable-user",
        })

    assert response.status_code == 502, response.text
    assert response.json() == {
        "code": "internal_server_error", "status": 502,
        "message": "消息会话与意图持久化失败，请稍后重试。",
    }
    trace = isolated_workflow.call_args.args[0]
    assert any(entry.node == "persist_intent" and entry.decision == "error" for entry in trace)


@pytest.mark.parametrize("product_type,intent,product_number,raw", [
    ("option", "query_order_status", 0, "期权查订单"),
    ("option_close", "close_order_order_query", 0, "查询 CO-20260304-ABCD1234"),
    ("swap", "query_order_status", 1, "互换查订单"),
])
def test_business_branch_persists_latest_intent_after_operate(
    monkeypatch: pytest.MonkeyPatch, isolated_workflow: AsyncMock,
    product_type: str, intent: str, product_number: int, raw: str,
) -> None:
    from app.subgraphs.close.models import CloseIntentOutput
    from app.subgraphs.option.models import OptionIntentOutput
    from app.subgraphs.swap.models import SwapIntentOutput

    llm_outputs = {
        "option": {
            "app.subgraphs.option.intent.get_qwen_structured": intent_reply(OptionIntentOutput, type="query_order_status"),
        },
        "option_close": {
            "app.subgraphs.close.intent.get_qwen_thinking": intent_reply(CloseIntentOutput, type="close_order_order_query"),
        },
        "swap": {
            "app.subgraphs.swap.intent.get_qwen_thinking": intent_reply(SwapIntentOutput, type="query_order_status"),
        },
    }
    for factory, value in llm_outputs[product_type].items():
        llm = MagicMock()
        llm.with_structured_output.return_value.ainvoke = mock_ainvoke(value)
        monkeypatch.setattr(factory, lambda llm=llm: llm)

    events: list[str] = []
    saved_requests: list[dict] = []
    operate_requests = []

    class BusinessClient:
        async def operate(self, req):
            events.append("operate")
            operate_requests.append(req)
            return {"code": 0, "data": "BACKEND_CARD"}

    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", BusinessClient)
    monkeypatch.setattr("app.subgraphs.close.backend.OptionClientHttpx", BusinessClient)
    monkeypatch.setattr("app.subgraphs.swap.backend.SwapClientHttpx", BusinessClient)

    def handler(request: httpx.Request) -> httpx.Response:
        events.append("set-intent")
        saved_requests.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0})

    monkeypatch.setattr(app_main, "MessageClientHttpx", lambda: MessageClientHttpx(
        base_url="https://java.invalid", token="", transport=httpx.MockTransport(handler),
    ))
    with TestClient(app_main.app) as client:
        response = client.post("/v1/workflows/run", json={
            "inputs": {
                "raw_content": raw, "conversation_id": "(\\existing-id\\\\)",
                "message_id": 75, "room_id": "test-room",
            },
            "user": "stable-user",
        })

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "succeeded"
    assert response.json()["data"]["outputs"]["product_type"] == product_type
    assert response.json()["answer"] == "BACKEND_CARD"
    assert events == ["operate", "set-intent"]
    assert operate_requests[0].message_id == 75  # /operate 仍使用整数
    assert saved_requests == [{
        "conversationId": "(\\existing-id\\\\)", "messageId": "75",
        "intent": intent, "productType": product_number, "orderIds": [],
    }]


async def test_http_response_waits_for_set_intent_acknowledgement(
    monkeypatch: pytest.MonkeyPatch, isolated_workflow: AsyncMock,
) -> None:
    started = asyncio.Event()
    acknowledged = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await acknowledged.wait()
        return httpx.Response(200, json={"code": 0})

    monkeypatch.setattr(app_main, "MessageClientHttpx", lambda: MessageClientHttpx(
        base_url="https://java.invalid", token="", transport=httpx.MockTransport(handler),
    ))
    async with app_main.lifespan(app_main.app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_main.app), base_url="http://test",
    ) as client:
        pending = asyncio.create_task(client.post("/v1/workflows/run", json={
            "inputs": {"raw_content": "你好", "conversation_id": "", "message_id": 42},
            "user": "stable-user",
        }))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            assert not pending.done()
            isolated_workflow.assert_not_awaited()
        finally:
            acknowledged.set()
        response = await asyncio.wait_for(pending, timeout=5)
        assert response.status_code == 200, response.text


async def test_direct_graph_without_factory_does_not_write_messages(
    monkeypatch: pytest.MonkeyPatch, isolated_workflow: AsyncMock,
) -> None:
    send = AsyncMock(side_effect=AssertionError("unexpected external request"))
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    final = await build_main_graph().ainvoke({"raw_text": "你好"})
    assert final.get("error") is None
    assert final["reply_text"]
    send.assert_not_awaited()


async def test_next_turn_recovers_after_set_intent_failure_with_checkpoint(
    isolated_workflow: AsyncMock,
) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(401 if payload["messageId"] == "1" else 200, json={"code": 0})

    graph = build_main_graph(
        checkpointer=InMemorySaver(), message_client_factory=lambda: MessageClientHttpx(
            base_url="https://java.invalid", token="", transport=httpx.MockTransport(handler),
        ),
    )
    config = {"configurable": {"thread_id": "opaque-id"}}
    first = await graph.ainvoke({
        "raw_text": "你好", "conversation_id": "opaque-id", "message_id": 1,
    }, config=config)
    assert first["error"].node == "persist_intent"
    second = await graph.ainvoke({
        "raw_text": "你好", "conversation_id": "opaque-id", "message_id": 2,
    }, config=config)
    assert second.get("error") is None
    assert second["reply_text"]
    assert [req["messageId"] for req in requests] == ["1", "2"]
