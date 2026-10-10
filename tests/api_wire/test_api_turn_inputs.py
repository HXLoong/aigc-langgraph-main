"""真实 API + 主图 + checkpoint 的当轮输入隔离回归。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import aiomysql
import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.api.routes import router
from app.graph.main import build_main_graph
from app.graph.state import Message, TickerCandidate
from app.nodes import fast_query
from app.subgraphs.swap import backend
from app.tools.goats_agent_client import GoatsAgentClientHttpx
from app.tools.option_client import OptionClientHttpx
from app.tools.swap_client import SwapClientHttpx
from tests.joint_support import joint_model

CONFIG = {"configurable": {"thread_id": "turn-inputs"}}
ORDER_ID = "H-20260915-0000000001"
IMAGE = {"type": "image", "remote_url": "http://files.test/order.png"}


@pytest.fixture
async def turn_api(monkeypatch):
    connection = MagicMock()
    connection.cursor.return_value.__aenter__.return_value.executemany = AsyncMock()
    monkeypatch.setattr(aiomysql, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", lambda: joint_model("swap", "query_order_status"))
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.startswith("/api/internal/agent/"):
            return httpx.Response(200, json={"errCode": {"code": 200}, "data": {}})
        return httpx.Response(200, json={"code": 0, "data": "本轮后端回执"})

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(fast_query, "_make_agent_client", lambda: GoatsAgentClientHttpx(
        "http://goats.test", "test-id", "test-secret", "test-salt", transport=transport,
    ))
    monkeypatch.setattr(fast_query, "_make_option_client", lambda: OptionClientHttpx(
        base_url="http://option.test", token="test-only", transport=transport, dry_run=False,
    ))
    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: SwapClientHttpx(
        base_url="http://swap.test", token="test-only", transport=transport, dry_run=False,
    ))
    saver = InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[
        ("app.graph.state", name) for name in ("TickerCandidate", "Message", "TraceEntry")
    ] + [("app.extraction.fields", "FieldRecord")]))
    graph = build_main_graph(checkpointer=saver)
    await graph.aupdate_state(CONFIG, {
        "tickers": [TickerCandidate(windCode="600519.SH", from_goats=True)],
        "place_params": {"orderList": [{"placeOrderWindCode": "600519.SH"}]},
        "cancel_params": {"orderList": [{"orderId": ORDER_ID}]},
        "history_messages": [Message(role="user", content="历史业务上下文")],
    })
    api = FastAPI()
    api.include_router(router)
    api.state.main_graph = graph
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://api.test") as client:
        yield client, graph, requests


async def send(client, inputs):
    response = await client.post("/v1/workflows/run", json={
        "conversation_id": "turn-inputs", "user": "test-user",
        "inputs": {"roomId": "test-room", "messageId": 123, **inputs},
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["data"]["status"] == "succeeded", result
    return result


@pytest.mark.parametrize("first_inputs,first_node", [
    ({"fastQuery": "1", "robotVersion": "V2"}, "quick_inquiry"),
    ({"existingCommand": "1", "atBot": "0"}, "existing_command_query"),
    ({"files": [IMAGE], "robotVersion": "V2"}, "prepare_input"),
])
async def test_omitted_nonversion_turn_inputs_restore_normal_route(turn_api, first_inputs, first_node):
    client, graph, requests = turn_api
    await send(client, {
        "rawContent": "首轮输入", "quoteContent": f"单号：{ORDER_ID}",
        "quoteAppinfo": "old-quote-metadata", **first_inputs,
    })
    first = (await graph.aget_state(CONFIG)).values
    assert first_node in [entry.node for entry in first["trace"]]
    requests.clear()
    result = await send(client, {"rawContent": f"查订单{ORDER_ID}", "robotVersion": "V2"})
    second = (await graph.aget_state(CONFIG)).values
    assert "swap_query_order" in [entry.node for entry in second["trace"]]
    if first_node != "prepare_input":
        assert first_node not in [entry.node for entry in second["trace"]]
    else:
        assert "图片" in first["reply_text"]
    assert result["answer"] == "本轮后端回执"
    assert len(requests) == 1
    assert requests[0][1]["type"] == "query_order_status"
    assert "quoteContent" not in requests[0][1]
    assert "quoteAppinfo" not in requests[0][1]
    for key in ("fast_query", "existing_command", "at_bot", "quote_content", "quote_appinfo"):
        assert second[key] is None
    assert second["input_files"] == []
    assert second["robot_version"] == "V2"
    # ADR 0024 D2：业务对象 per-turn，不再跨轮残留（跨轮记忆只有 history_messages）
    for key in ("tickers", "place_params", "cancel_params"):
        assert second[key] is None
    assert second["history_messages"][:len(first["history_messages"])] == first["history_messages"]


async def test_omitted_current_version_does_not_reuse_previous_v2(turn_api):
    client, graph, requests = turn_api
    await send(client, {"rawContent": f"查订单{ORDER_ID}", "robotVersion": "V2"})
    assert len(requests) == 1
    requests.clear()
    result = await send(client, {"rawContent": f"查订单{ORDER_ID}"})
    state = (await graph.aget_state(CONFIG)).values
    assert state["robot_version"] is None
    assert state["entry_branch"] == "ignore"
    assert result["answer"] == "IGNORE_REQUEST_NOT_REPLY_USER"
    assert not requests
    assert not {"parse_instruction", "swap_query_order"}.intersection(
        entry.node for entry in state["trace"]
    )


@pytest.mark.parametrize("inputs,expected", [
    ({}, ""),
    ({"messageContent": "本轮消息正文"}, "本轮消息正文"),
    ({"rawContent": "", "messageContent": "本轮消息正文"}, ""),
    ({"raw_content": "显式正文"}, "显式正文"),
])
async def test_current_text_defaults_after_message_fallback(turn_api, inputs, expected):
    client, graph, _ = turn_api
    await send(client, {"rawContent": "上轮正文", "messageContent": "上轮消息"})
    await send(client, inputs)
    state = (await graph.aget_state(CONFIG)).values
    assert state["raw_text"] == expected
    assert state["message_content"] == inputs.get("messageContent", "")


@pytest.mark.parametrize("inputs,node", [
    ({"fast_query": "1", "at_bot": False, "robot_version": "V2"}, "quick_inquiry"),
    ({"existing_command": "1", "at_bot": 0}, "existing_command_query"),
    ({"fastQuery": "0", "existingCommand": "1", "atBot": "1", "robotVersion": "V2"}, "swap_query_order"),
    ({"sysFiles": [IMAGE], "robotVersion": "V2"}, "prepare_input"),
])
async def test_explicit_current_inputs_override_defaults(turn_api, inputs, node):
    client, graph, requests = turn_api
    await send(client, {"rawContent": "上轮正文", "fastQuery": "1", "robotVersion": "V2"})
    requests.clear()
    await send(client, {"rawContent": f"查订单{ORDER_ID}", "quoteContent": "本轮引用",
                        "quoteAppinfo": "new-meta", **inputs})
    state = (await graph.aget_state(CONFIG)).values
    assert node in [entry.node for entry in state["trace"]]
    assert state["quote_content"] == "本轮引用"
    assert state["quote_appinfo"] == "new-meta"
    assert state["input_files"] == inputs.get("sysFiles", [])
    if node not in {"existing_command_query", "prepare_input"}:
        assert requests[-1][1]["quoteContent"] == "本轮引用"
        assert requests[-1][1]["quoteAppinfo"] == "new-meta"
