"""业务入口必须恰好三条边；会话保护在分流前完成且不触发业务 IO。"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import main
from app.graph.retry import io_node
from app.graph.safe_node import safe_node
from app.graph.state import Message, TraceEntry


def test_compiled_entry_has_exactly_three_business_edges():
    graph = main.build_main_graph().get_graph()
    outgoing = [edge for edge in graph.edges if edge.source == "entry_route"]
    assert len(outgoing) == 3
    assert {edge.target for edge in outgoing} == {
        "quick_inquiry", "existing_command_query", "pre_route",
    }
    assert {edge.target for edge in graph.edges if edge.source == "ingest"} == {
        "entry_route", "render",
    }


@pytest.mark.parametrize("flags,expected", [
    ({"fast_query": "1", "existing_command": "1", "at_bot": "0"}, "quick_inquiry"),
    ({"existing_command": "1", "at_bot": "0"}, "existing_command_query"),
    ({"existing_command": "1", "at_bot": "1"}, "pre_route"),
    ({}, "pre_route"),
])
def test_business_selector_has_no_session_exit(flags, expected):
    assert main._route_entry({**flags, "session_status": "expired"}) == expected


@pytest.mark.parametrize("flags", [
    {"fast_query": "1"}, {"existing_command": "1", "at_bot": "0"}, {},
])
async def test_expired_session_stops_before_every_business_branch(monkeypatch, flags):
    ingest = importlib.import_module("app.nodes.ingest")
    monkeypatch.setattr(ingest, "time", lambda: 2000)
    monkeypatch.setattr(ingest, "get_settings", lambda: SimpleNamespace(
        conversation_idle_timeout_seconds=1800,
    ))
    called = []

    @io_node
    async def forbidden(state):
        called.append("business")
        raise AssertionError("expired session entered business processing")

    for name in ("entry_route", "quick_inquiry", "existing_command_query",
                 "pre_route", "intent_route"):
        monkeypatch.setattr(main, name, forbidden, raising=False)
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    result = await main.build_main_graph().ainvoke({
        **flags, "raw_text": "确认下单", "last_activity_at": 100,
        "history_messages": [Message(role="assistant", content="旧订单")],
        "last_confirmed_params": {"order_ids": ["Q-old"]},
        "conversation_orders": [{"orderId": "Q-old"}],
        "reply_text": "上一轮成功卡", "api_code": 0, "api_result": "上一轮成功卡",
        "place_params": {"orderList": [{"orderId": "Q-old"}]},
    })
    assert not called
    assert result["session_status"] == "expired"
    assert "会话已过期" in result["reply_text"]
    assert result["last_confirmed_params"] is None and result["conversation_orders"] == []
    assert result["place_params"] is None and result["api_result"] is None
    assert all(message.content != "旧订单" for message in result["history_messages"])
    assert any(e.node == "ingest" and e.decision == "session:expired" for e in result["trace"])


async def test_ingest_failure_does_not_continue_to_business(monkeypatch):
    @safe_node
    async def broken_ingest(state):
        raise ValueError("entry failed")

    called = []

    @io_node
    async def forbidden(state):
        called.append("business")
        return {"reply_text": "不应进入业务分支"}

    monkeypatch.setattr(main, "ingest", broken_ingest)
    for name in ("entry_route", "quick_inquiry", "existing_command_query", "pre_route"):
        monkeypatch.setattr(main, name, forbidden, raising=False)
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    result = await main.build_main_graph().ainvoke({"raw_text": "x", "fast_query": "1"})
    assert not called
    assert result["error"].node == "broken_ingest"
    assert result["reply_text"] and result["reply_text"] != "不应进入业务分支"


@pytest.mark.parametrize("flags,chosen", [
    ({"fast_query": "1", "existing_command": "1", "at_bot": "0"}, "quick_inquiry"),
    ({"existing_command": "1", "at_bot": "0"}, "existing_command_query"),
    ({"existing_command": "1", "at_bot": "1"}, "pre_route"),
])
async def test_valid_session_records_choice(monkeypatch, flags, chosen):
    calls = []

    @safe_node
    async def quick(state):
        calls.append("quick_inquiry")
        return {"reply_text": "快速询价结果"}

    @io_node
    async def existing(state):
        calls.append("existing_command_query")
        return {"reply_text": "IGNORE_REQUEST_NOT_REPLY_USER"}

    @io_node
    async def intent(state):
        calls.append("intent_route")
        return {"product_type": "unknown"}

    monkeypatch.setattr(main, "quick_inquiry", quick)
    monkeypatch.setattr(main, "existing_command_query", existing)
    monkeypatch.setattr(main, "intent_route", intent)
    monkeypatch.setattr(main, "pre_route", AsyncMock(return_value={}))
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    result = await main.build_main_graph().ainvoke({**flags, "raw_text": "业务输入"})
    route = [e for e in result["trace"] if e.node == "entry_route"]
    assert len(route) == 1 and route[0].decision == chosen
    assert result["trace"][0].node == "ingest"
    assert route[0].elapsed_ms is not None
    expected = ["intent_route"] if chosen == "pre_route" else [chosen]
    assert calls == expected


async def test_router_trace_resets_between_turns_without_erasing_ingest(monkeypatch):
    @safe_node
    async def reply(state):
        return {"reply_text": "后端回复"}

    monkeypatch.setattr(main, "quick_inquiry", reply)
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    graph = main.build_main_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "entry-route-turns"}}
    for number in (1, 2):
        result = await graph.ainvoke({
            "raw_text": f"第{number}轮", "message_id": number, "fast_query": "1",
            "trace": [TraceEntry(node="previous_turn")],
        }, config=config)
        nodes = [e.node for e in result["trace"]]
        assert nodes[:2] == ["ingest", "entry_route"]
        assert nodes.count("entry_route") == 1 and "previous_turn" not in nodes
