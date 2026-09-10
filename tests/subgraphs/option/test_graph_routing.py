"""option 子图路由测试 · intent → conditional → 7 个 extract 节点 / unknown（Dify DSL v2）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import build_option_graph
from app.subgraphs.option import extract_cancel as cancel_module
from app.subgraphs.option import extract_cancel_place as cancel_place_module
from app.subgraphs.option import extract_confirm_cancel as confirm_cancel_module
from app.subgraphs.option import extract_confirm_place as confirm_place_module
from app.subgraphs.option import extract_inquiry as inquiry_module
from app.subgraphs.option import extract_place as place_module
from app.subgraphs.option import extract_query as query_module
from app.subgraphs.option import intent as intent_module
from app.subgraphs.option.models import (
    OptionCancelParams,
    OptionCancelPlaceParams,
    OptionConfirmCancelParams,
    OptionConfirmPlaceParams,
    OptionInquiryParams,
    OptionIntentOutput,
    OptionOrderItem,
    OptionOrderItemWithFastExec,
    OptionPlaceParams,
    OptionQueryParams,
)

#: 不含 conversation_id/user_id/room_id——保持 call_option_backend() 的早退门禁
#: 生效（三者缺一即返回 {}），路由测试只关心 intent → 节点分发 + state 业务字段
#: 写入是否正确，不应该在这里触发真实后端 HTTP 调用（后端 payload 组装单独在
#: test_extract_*.py / test_business_params.py 覆盖）。
_BASE_STATE = {
    "message_id": 1,
    "message_content": "x",
}


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
    if hasattr(module, "call_option_backend"):
        monkeypatch.setattr(
            module,
            "call_option_backend",
            AsyncMock(
                return_value={"api_code": 0, "api_result": "backend reply"}
            ),
        )


def _patch_intent(monkeypatch: pytest.MonkeyPatch, intent_type: str) -> None:
    _patch(
        monkeypatch,
        intent_module,
        OptionIntentOutput(type=intent_type),  # type: ignore[arg-type]
        fn="get_qwen_structured",
    )


@pytest.mark.asyncio
async def test_new_inquiry_routes_to_extract_inquiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_intent(monkeypatch, "new_inquiry")
    _patch(
        monkeypatch,
        inquiry_module,
        OptionInquiryParams(orderList=[OptionOrderItem(stockCode="腾讯")]),
    )
    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "腾讯询价"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_extract_inquiry" in trace_nodes
    assert final.get("intent") == "new_inquiry"


@pytest.mark.asyncio
async def test_place_order_from_quote_routes_to_extract_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """place_order_from_quote → option_extract_place 真节点。"""
    _patch_intent(monkeypatch, "place_order_from_quote")
    _patch(
        monkeypatch,
        place_module,
        OptionPlaceParams(
            orderList=[OptionOrderItemWithFastExec(orderId="Q-1", orderType="市价单")]
        ),
    )

    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "市价下单"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_intent" in trace_nodes
    assert "option_extract_place" in trace_nodes
    assert "option_todo" not in trace_nodes
    assert final.get("intent") == "place_order_from_quote"
    assert final.get("place_params", {}).get("expected_action") == "place"


@pytest.mark.asyncio
async def test_confirm_order_routes_to_extract_confirm_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_intent(monkeypatch, "confirm_order")
    _patch(
        monkeypatch,
        confirm_place_module,
        OptionConfirmPlaceParams(orderList=[OptionOrderItem(orderId="Q-1")]),
    )
    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "确认下单"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_extract_confirm_place" in trace_nodes
    assert final.get("confirm", {}).get("action") == "place"


@pytest.mark.asyncio
async def test_cancel_order_request_routes_to_extract_cancel_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_intent(monkeypatch, "cancel_order_request")
    _patch(
        monkeypatch,
        cancel_place_module,
        OptionCancelPlaceParams(orderList=[OptionOrderItem(orderId="Q-1")]),
    )
    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "取消下单"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_extract_cancel_place" in trace_nodes
    assert final.get("cancel_params", {}).get("expected_action") == "cancel_request"


@pytest.mark.asyncio
async def test_request_cancel_order_routes_to_extract_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_intent(monkeypatch, "request_cancel_order")
    _patch(
        monkeypatch,
        cancel_module,
        OptionCancelParams(orderList=[OptionOrderItem(orderId="Q-1")]),
    )
    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "撤单 Q-1"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_extract_cancel" in trace_nodes
    assert final.get("cancel_params", {}).get("expected_action") == "request_cancel"


@pytest.mark.asyncio
async def test_confirm_cancel_order_routes_to_extract_confirm_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_intent(monkeypatch, "confirm_cancel_order")
    _patch(
        monkeypatch,
        confirm_cancel_module,
        OptionConfirmCancelParams(orderList=[OptionOrderItem(orderId="Q-1")]),
    )
    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "确认撤单"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_extract_confirm_cancel" in trace_nodes
    assert final.get("confirm", {}).get("action") == "cancel"


@pytest.mark.asyncio
async def test_query_order_status_routes_to_extract_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_intent(monkeypatch, "query_order_status")
    _patch(
        monkeypatch,
        query_module,
        OptionQueryParams(orderList=[OptionOrderItem(orderId="Q-1")]),
    )
    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "查询订单状态"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_extract_query" in trace_nodes


@pytest.mark.asyncio
async def test_unknown_intent_routes_to_option_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent 走 option_unknown 兜底（7 意图 : 7 真节点全到位）。"""
    _patch_intent(monkeypatch, "unknown_intent")
    graph = build_option_graph()
    final = await graph.ainvoke({**_BASE_STATE, "raw_text": "你好"})
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_unknown" in trace_nodes
    for unexpected in (
        "option_extract_inquiry",
        "option_extract_place",
        "option_extract_confirm_place",
        "option_extract_cancel_place",
        "option_extract_cancel",
        "option_extract_confirm_cancel",
        "option_extract_query",
    ):
        assert unexpected not in trace_nodes
