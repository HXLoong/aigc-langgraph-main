"""主图联合解析结果直达 Java，业务子图不再调用模型。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.main import build_main_graph
from app.llm.clients import _ChatLLM
from app.parsing.models import OptionInstruction


@pytest.mark.parametrize("amount", ["1000000", "100万"])
async def test_option_inquiry_uses_one_model_and_preserves_java_wire(monkeypatch, amount) -> None:
    """从主图入口检查模型次数、最终 wire 值及 Java 原始回执。"""
    model_calls = []
    requests = []
    result = OptionInstruction.model_validate({
        "product_type": "option", "intent": "new_inquiry", "confidence": 0.9,
        "evidence": [{"origin": "raw", "text": "询价"}],
        "orders": [{"stockCode": "茅台", "notionalAmount": amount}],
        "fields": [{"path": "orders.0.stockCode", "origin": "raw", "text": "茅台"},
                   {"path": "orders.0.notionalAmount", "origin": "raw", "text": "100万"}],
    })

    def structured(self, schema, **kwargs):
        """替换所有真实模型请求，避免旧路径意外联网。"""
        async def invoke(messages, **kwargs):
            """记录所有模型节点调用，不仅记录新联合解析节点。"""
            model_calls.append(schema)
            return result
        return SimpleNamespace(ainvoke=invoke)

    async def operate(self, req):
        """只替换 Java HTTP 出口，保留真实 DTO 装配。"""
        requests.append(req.model_dump(mode="json", exclude_none=True))
        return {"code": 0, "data": "Java inquiry card", "msg": ""}

    monkeypatch.setattr(_ChatLLM, "with_structured_output", structured)
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", operate)
    monkeypatch.setattr("app.nodes.persist.write_node_trace", AsyncMock())
    graph = build_main_graph(InMemorySaver())
    state = await graph.ainvoke({"raw_text": "茅台期权询价100万", "conversation_id": "joint-case",
        "message_id": 1, "room_id": "room", "user_id": "user"},
        config={"configurable": {"thread_id": "joint-case"}})
    assert state.get("error") is None
    assert len(model_calls) == len(requests) == 1
    assert requests[0]["type"] == "new_inquiry"
    expected = {"stockCode": "茅台"}
    if amount == "1000000":
        expected["notionalAmount"] = amount
    assert requests[0]["orderList"] == [expected]
    # API/Harness 看到实际出站值，原始账本依然能够复核模型提取。
    from app.api.routes import _state_to_outputs

    outputs = _state_to_outputs(state)
    assert outputs["place_params"]["orderList"] == [expected]
    assert state["field_records"]["option/parse.orderList.0.notionalAmount"].value == amount
    assert outputs["backend_request"] == requests[0]
    assert state["api_result"] == state["reply_text"] == "Java inquiry card"
