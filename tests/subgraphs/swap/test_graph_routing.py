"""互换消费唯一解析结果，全部动作保持单路由和失败停止。"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.state import ErrorInfo
from app.subgraphs.swap.graph import (
    _route_after_apply_picks,
    _route_after_place_order,
    _route_after_swap_intent,
    build_swap_graph,
)
from tests.joint_support import instruction_data


@pytest.mark.parametrize("intent,target", [
    ("place_order_request", "swap_place_order"), ("cancel_order_request", "swap_cancel"),
    ("confirm_order", "swap_confirm"), ("confirm_cancel_order", "swap_confirm"),
    ("confirm_modify_order", "swap_confirm"), ("query_order_status", "swap_query_order"),
    ("unknown_intent", "swap_unknown"),
])
def test_single_action_dispatch(intent, target):
    """同一消息只选择一个动作节点。"""
    assert _route_after_swap_intent({"intent": intent}) == target


@pytest.mark.parametrize("route", [_route_after_swap_intent, _route_after_place_order, _route_after_apply_picks])
def test_error_stops_business_dispatch(route):
    """任一准备阶段错误都不得进入业务提交。"""
    assert route({"error": ErrorInfo(node="test", type="ValueError", message="invalid", code="E2")}) == "swap_unknown"


async def test_graph_preserves_java_receipt_without_models(monkeypatch):
    """从子图入口到 Java 只消费已给的解析结果。"""
    from app.llm.clients import _ChatLLM

    model = MagicMock(side_effect=AssertionError("子图不能调用模型"))
    monkeypatch.setattr(_ChatLLM, "with_structured_output", model)
    backend = AsyncMock(return_value={"code": 0, "data": "Java raw reply"})
    monkeypatch.setattr("app.tools.swap_client.SwapClientHttpx.operate", backend)
    raw = "买茅台1000股"
    state = {"raw_text": raw, "conversation_id": "test", "room_id": "r", "user_id": "u", "message_id": 1,
        "parsed_instruction": instruction_data("swap", "place_order_request", raw,
            orders=[{"placeOrderWindCode": "茅台", "placeOrderQuantity": 1000}])}
    out = await build_swap_graph().ainvoke(state)
    assert not out.get("error")
    assert out["api_result"] == "Java raw reply"
    assert backend.await_count == 1
    model.assert_not_called()
