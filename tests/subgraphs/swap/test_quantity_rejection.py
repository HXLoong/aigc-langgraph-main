"""Non-positive quantities stop the real swap graph before its backend write boundary."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph.state import AgentState, ErrorInfo
from app.nodes.render import render
from app.subgraphs.swap import backend, intent, place_order
from app.subgraphs.swap.graph import build_swap_graph
from app.subgraphs.swap.models import SwapIntentOutput
from app.subgraphs.swap.normalize import normalize_field
from app.tools.receipts import SERVICE_UNAVAILABLE
from tests.intent_fixtures import intent_reply, mock_ainvoke

_QUANTITY_REPLY = "委托数量必须大于零，请核对后重新发送。"


@pytest.mark.parametrize("field", [
    "placeOrderQuantity", "placeOrderQuantityHand", "placeOrderQuantityTotal", "placeOrderDisplayQty",
])
@pytest.mark.parametrize("value", ["-34250", "0"])
def test_non_positive_quantity_has_typed_error_without_input_value(field: str, value: str) -> None:
    with pytest.raises(ValueError) as captured:
        normalize_field(field, value)
    assert type(captured.value).__name__ == "NonPositiveQuantityError"
    assert captured.value.field == field
    assert value not in str(captured.value)


@pytest.mark.parametrize("field", [
    "placeOrderPrice", "placeOrderNotional", "placeOrderMaxVol", "placeOrderPovPercent",
    "placeOrderTotalPovPercent",
])
@pytest.mark.parametrize("value", ["-3", "0"])
def test_other_non_positive_numbers_keep_existing_validation(field: str, value: str) -> None:
    with pytest.raises(ValueError) as captured:
        normalize_field(field, value)
    assert type(captured.value) is ValueError


def _candidate(value: str) -> dict[str, Any]:
    return {"value": value, "evidence": value, "confidence": 0.99, "origin": "raw"}


def _boundaries(monkeypatch: pytest.MonkeyPatch, quantities: list[str]) -> tuple[AgentState, AsyncMock]:
    raw = "；".join(f"买入 600519.SH {quantity}股，市价" for quantity in quantities)
    intent_llm = MagicMock()
    intent_llm.with_structured_output.return_value.ainvoke = mock_ainvoke(
        intent_reply(SwapIntentOutput, type="place_order_request"),
    )
    monkeypatch.setattr(intent, "get_qwen_thinking", lambda: intent_llm)
    candidates = place_order.CANDIDATE_MODEL.model_validate({"orderList": [{
        "placeOrderWindCode": _candidate("600519.SH"),
        "placeOrderQuantity": _candidate(f"{quantity}股"),
        "placeOrderOrderDirection": _candidate("买入"),
        "placeOrderPriceType": _candidate("市价"),
    } for quantity in quantities]})
    extract_llm = MagicMock()
    extract_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=candidates)
    monkeypatch.setattr(place_order, "get_qwen_complex", lambda: extract_llm)
    operate = AsyncMock(return_value={"code": 0, "data": "Java 原始订单回执"})
    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: MagicMock(operate=operate))
    return {
        "raw_text": raw, "message_content": raw, "product_type": "swap",
        "swap_input_mode": "text", "conversation_id": "quantity-test", "message_id": 227,
        "user_id": "quantity-user", "room_id": "quantity-room", "swap_counterparties": [],
    }, operate


async def _run_graph(state: AgentState) -> dict[str, Any]:
    graph = StateGraph(AgentState)
    graph.add_node("swap", build_swap_graph())
    graph.add_node("render", render)
    graph.add_edge(START, "swap")
    graph.add_edge("swap", "render")
    graph.add_edge("render", END)
    return await graph.compile().ainvoke(state)


@pytest.mark.parametrize("quantities", [["-34250"], ["0"], ["100", "-3"]])
async def test_invalid_quantity_cascades_to_specific_reply_without_backend_write(
    monkeypatch: pytest.MonkeyPatch, quantities: list[str],
) -> None:
    state, operate = _boundaries(monkeypatch, quantities)
    result = await _run_graph(state)
    operate.assert_not_awaited()
    assert result["error"].type == "NonPositiveQuantityError"
    assert result["error"].node == "swap_normalize"
    assert result["reply_text"] == _QUANTITY_REPLY
    nodes = [entry.node for entry in result["trace"]]
    assert "swap_unknown" in nodes
    assert "swap_place_order_submit" not in nodes
    assert result["trace"][-1].decision == "error:swap_non_positive_quantity"


async def test_positive_quantity_reaches_backend_and_preserves_java_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, operate = _boundaries(monkeypatch, ["100"])
    result = await _run_graph(state)
    operate.assert_awaited_once()
    assert operate.await_args.args[0].order_list[0].place_order_quantity == 100
    assert not result.get("error")
    assert result["reply_text"] == result["api_result"] == "Java 原始订单回执"


@pytest.mark.parametrize("as_dict", [False, True])
@pytest.mark.parametrize("code,receipt,expected", [
    (0, "Java: 正在处理，请勿重复提交", "Java: 正在处理，请勿重复提交"),
    (400, "Java: 订单数量不合法", "Java: 订单数量不合法"),
    (500, "Java: 原始系统异常", SERVICE_UNAVAILABLE),
])
async def test_java_receipt_precedes_quantity_error(
    code: int, receipt: str, expected: str, as_dict: bool,
) -> None:
    error = ErrorInfo(node="swap_normalize", type="NonPositiveQuantityError",
                      message="placeOrderQuantity 必须大于零")
    state: AgentState = {"product_type": "swap", "api_code": code, "api_result": receipt,
                         "error": error.model_dump() if as_dict else error}
    result = await render(state)
    assert result["reply_text"] == expected
    assert result["trace"][-1].decision == "api_result"
    assert state["api_result"] == receipt


@pytest.mark.parametrize("product,error_type", [
    ("option", "NonPositiveQuantityError"), ("option_close", "NonPositiveQuantityError"),
    ("swap", "ValueError"),
])
async def test_quantity_reply_does_not_replace_other_product_or_error_fallbacks(
    product: str, error_type: str,
) -> None:
    result = await render({"product_type": product, "error": {
        "type": error_type, "node": "other", "message": "必须大于零",
    }})
    assert result["reply_text"] == get_settings().default_reply
    assert result["trace"][-1].decision == "error:cascade_fail"
