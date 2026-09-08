"""swap 子图路由测试 · place_order_request → swap_place_order。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.state import TickerCandidate
from app.subgraphs.swap import backend as swap_backend_module
from app.subgraphs.swap import build_swap_graph
from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap import place_order as po_module
from app.subgraphs.swap.models import (
    SwapIntentOutput,
    SwapOrderItem,
    SwapPlaceOrderParams,
)
from app.subgraphs.ticker.resolver import TickerResolution


def _patch_resolver(
    monkeypatch: pytest.MonkeyPatch,
    candidates: list[TickerCandidate],
) -> None:
    resolution = TickerResolution(resolved=candidates, hitl_pending=[])
    monkeypatch.setattr(po_module, "resolve_ticker_full", AsyncMock(return_value=resolution))


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    value: object,
    fn: str = "get_qwen_thinking",
) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, fn, lambda: fake_base)


def _patch_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(return_value=MagicMock(code=0, data={}, msg=""))
    monkeypatch.setattr(swap_backend_module, "SwapClientHttpx", lambda: fake_client)


@pytest.mark.asyncio
async def test_place_order_request_routes_to_place_order_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """place_order_request → swap_place_order 真节点（不再走 todo）。"""
    _patch_resolver(
        monkeypatch,
        [
            TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True),
        ],
    )
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
        fn="get_qwen_complex",
    )
    _patch_backend(monkeypatch)

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
    assert any("700" in t.windCode and t.windCode.endswith(".HK") for t in tickers)


@pytest.mark.asyncio
async def test_other_intents_still_route_to_todo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent 走 swap_unknown 兜底（swap 子图主路由 7/7 意图全到位）。"""
    _patch(
        monkeypatch,
        intent_module,
        SwapIntentOutput(type="unknown_intent"),
    )
    graph = build_swap_graph()
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
    assert "swap_unknown" in trace_nodes
    assert "swap_place_order" not in trace_nodes
