"""swap 子图路由测试 · place_order_request → swap_place_order。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import build_swap_graph
from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap import place_order as po_module
from app.subgraphs.swap.models import (
    SwapIntentOutput,
    SwapOrderItem,
    SwapPlaceOrderParams,
)


def _patch(monkeypatch: pytest.MonkeyPatch, module: object, value: object) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, "get_qwen_structured", lambda: fake_base)


@pytest.mark.asyncio
async def test_place_order_request_routes_to_place_order_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """place_order_request → swap_place_order 真节点（不再走 todo）。"""
    _patch(
        monkeypatch,
        intent_module,
        SwapIntentOutput(type="place_order_request"),
    )
    _patch(
        monkeypatch,
        po_module,
        SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(
                    placeOrderWindCode="腾讯",
                    placeOrderQuantity=1000,
                )
            ]
        ),
    )

    graph = build_swap_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "互换下单 腾讯 1000 股",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "swap_intent" in trace_nodes
    assert "swap_place_order" in trace_nodes
    assert "swap_todo" not in trace_nodes
    assert final.get("intent") == "place_order_request"
    assert final.get("place_params", {}).get("expected_action") == "place"
    # ticker 集成验证
    tickers = final.get("tickers", [])
    assert any(t.windCode == "00700.HK" for t in tickers)


@pytest.mark.asyncio
async def test_other_intents_still_route_to_todo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """剩余 6 个意图（如 cancel_order_request）当前无真节点 → todo。"""
    _patch(
        monkeypatch,
        intent_module,
        SwapIntentOutput(type="cancel_order_request"),
    )
    graph = build_swap_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "撤 H-20260304-0001",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "swap_todo" in trace_nodes
    assert "swap_place_order" not in trace_nodes
