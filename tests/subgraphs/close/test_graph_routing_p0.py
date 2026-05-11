"""close 子图 P0 路由测试 · close_order_request → close_place_close。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.models import (
    CloseIntentOutput,
    CloseOrderItem,
    ClosePlaceParams,
)


def _patch(monkeypatch: pytest.MonkeyPatch, module: object, value: object) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, "get_qwen_structured", lambda: fake_base)


@pytest.mark.asyncio
async def test_close_order_request_routes_to_place_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_order_request → close_place_close 真节点（不再走 todo）。"""
    _patch(
        monkeypatch,
        intent_module,
        CloseIntentOutput(type="close_order_request"),
    )
    _patch(
        monkeypatch,
        pc_module,
        ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="CO-20260304-AAAA0001",
                    closeOrderNotionalDelta="2000000",
                    closeOrderType="市价单",
                )
            ]
        ),
    )

    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "平 CO-20260304-AAAA0001 200万 市价",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_intent" in trace_nodes
    assert "close_place_close" in trace_nodes
    assert "close_todo" not in trace_nodes
    assert "close_holding_query" not in trace_nodes
    assert final.get("intent") == "close_order_request"
    close_params = final.get("close_params", {})
    assert close_params.get("closeOrderList")
    assert (
        close_params["closeOrderList"][0]["orderId"]
        == "CO-20260304-AAAA0001"
    )
