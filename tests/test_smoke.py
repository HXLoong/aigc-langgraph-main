"""主图冒烟覆盖三产品、一次模型、真实 DTO 路径和多轮隔离。"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.main import build_main_graph
from tests.joint_support import joint_model


@pytest.mark.parametrize("product,intent,raw,orders", [
    ("swap", "place_order_request", "互换买茅台100股", [{"placeOrderWindCode": "茅台", "placeOrderQuantity": 100}]),
    ("option", "new_inquiry", "期权询价茅台1M", [{"stockCode": "茅台", "tenor": "1M"}]),
    ("option_close", "close_order_request", "CO-20260922-ABCDEF12全部平仓", [{"orderId": "CO-20260922-ABCDEF12", "confirmFullClose": True}]),
])
async def test_real_main_graph_uses_one_model_and_one_business_call(monkeypatch, product, intent, raw, orders):
    """只替换外部 IO，检查实际主图、子图、回执与历史。"""
    calls = []
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", lambda: joint_model(product, intent, orders=orders, calls=calls))
    backend = AsyncMock(return_value={"code": 0, "data": "Java receipt"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    monkeypatch.setattr("app.tools.swap_client.SwapClientHttpx.operate", backend)
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.query_close_orders", AsyncMock(return_value={"code": 0, "data": []}))
    monkeypatch.setattr("app.nodes.persist.write_node_trace", AsyncMock())
    result = await build_main_graph().ainvoke({"raw_text": raw, "conversation_id": "smoke", "message_id": 1,
        "user_id": "u", "room_id": "r", "robot_version": "V2", "at_bot": True})
    assert not result.get("error"), result
    assert len(calls) == 1 and backend.await_count == 1
    assert (result["product_type"], result["intent"]) == (product, intent)
    assert result["reply_text"] == result["api_result"] == "Java receipt"
    assert [(m.role, m.content) for m in result["history_messages"]] == [("user", raw), ("assistant", "Java receipt")]


async def test_unknown_turns_preserve_history_but_reset_trace(monkeypatch):
    """每轮独立解析，旧 trace 不重复，会话历史继续按原顺序保留。"""
    calls = []
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", lambda: joint_model("unknown", "unknown_intent", calls=calls))
    monkeypatch.setattr("app.nodes.persist.write_node_trace", AsyncMock())
    graph = build_main_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "smoke-history"}}
    results = [await graph.ainvoke({"raw_text": f"第{index}轮闲聊", "conversation_id": "smoke-history",
        "message_id": index, "robot_version": "V2", "at_bot": True}, config=config) for index in (1, 2)]
    assert len(calls) == 2
    for result in results:
        assert not result.get("error"), result
        nodes = [entry.node for entry in result["trace"]]
        assert nodes.count("ingest") == nodes.count("parse_instruction") == nodes.count("render") == 1
        assert "fallback" in nodes
    assert len(results[-1]["history_messages"]) == 4
