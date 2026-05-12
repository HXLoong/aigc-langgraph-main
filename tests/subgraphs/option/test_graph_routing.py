"""option 子图路由测试 · intent → conditional → extract / todo。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import build_option_graph
from app.subgraphs.option import (
    extract_place_or_modify as epm_module,
)
from app.subgraphs.option import intent as intent_module
from app.subgraphs.option.models import (
    OptionIntentOutput,
    OptionOrderItem,
    OptionPlaceOrModifyParams,
)


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    value: object,
    fn: str = "get_qwen_structured",
) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, fn, lambda: fake_base)


@pytest.mark.asyncio
async def test_place_order_from_quote_routes_to_extract_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """place_order_from_quote → option_extract_place_or_modify 真节点。"""
    _patch(
        monkeypatch,
        intent_module,
        OptionIntentOutput(type="place_order_from_quote"),
    )
    _patch(
        monkeypatch,
        epm_module,
        OptionPlaceOrModifyParams(
            orderList=[OptionOrderItem(orderId="Q-1", orderType="市价单")]
        ),
        fn="get_qwen_thinking",
    )

    graph = build_option_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "市价下单",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_intent" in trace_nodes
    assert "option_extract_place_or_modify" in trace_nodes
    assert "option_todo" not in trace_nodes
    assert final.get("intent") == "place_order_from_quote"
    assert final.get("place_params", {}).get("expected_action") == "place"


@pytest.mark.asyncio
async def test_request_modify_routes_to_extract_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """request_modify_order → option_extract_place_or_modify（共用 schema）。"""
    _patch(
        monkeypatch,
        intent_module,
        OptionIntentOutput(type="request_modify_order"),
    )
    _patch(
        monkeypatch,
        epm_module,
        OptionPlaceOrModifyParams(
            orderList=[OptionOrderItem(orderId="Q-1", limitPrice=10)]
        ),
        fn="get_qwen_thinking",
    )

    graph = build_option_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "改限价 10",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_extract_place_or_modify" in trace_nodes
    assert final.get("place_params", {}).get("expected_action") == "modify"


@pytest.mark.asyncio
async def test_unknown_intent_routes_to_option_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent 走 option_unknown 兜底（option 子图 6/6 真节点全到位）。"""
    _patch(
        monkeypatch,
        intent_module,
        OptionIntentOutput(type="unknown_intent"),
    )
    graph = build_option_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "你好",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_unknown" in trace_nodes
    assert "option_extract_place_or_modify" not in trace_nodes
    assert "option_extract_inquiry" not in trace_nodes
