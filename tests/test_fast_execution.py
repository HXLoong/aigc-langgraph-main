"""三条业务链共用最大跟量判断；纯归一化测试不调用模型或后端。"""
from __future__ import annotations

from typing import Any

import pytest

from app.extraction.candidates import candidate_model
from app.subgraphs.close.normalization import normalize_place_candidates
from app.subgraphs.close.reference_parser import parse_reference_message
from app.subgraphs.option.place_params import parse_place_params_with_lineage
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates
from tests.subgraphs.close.candidate_fixtures import close_candidates

ORDER = "CO-20260921-ABCDEF12"


def cell(value: str, *, origin: str = "raw", reference: str | None = None) -> dict[str, Any]:
    return {"value": value, "evidence": value, "origin": origin,
            "reference": reference, "confidence": 1.0}


def swap_rows(rows, sources):
    return normalize_candidates(
        candidate_model(SwapPlaceOrderParams).model_validate({"orderList": rows}), sources,
    )


@pytest.mark.parametrize("text,ratio,expected", [
    ("最大跟量", False, True),
    ("最大跟量 POV9", True, True),
    ("尽快成交", False, True),
    ("尽快成交 POV9", True, False),
    ("尽快成交 跟量比例9%", False, False),
    ("尽快成交，比例已填写", True, False),
    ("尽快成交 POV0", False, False),
    ("尽快成交，平50%", False, True),
    ("普通跟量", False, False),
    ("市价跟量", False, False),
    ("市价下单", False, False),
    ("不要最大跟量", False, False),
    ("最大跟量不要", False, False),
    ("如果可以就最大跟量", False, False),
    ("最大跟量吗", False, False),
    ("最大跟量还是POV9", True, False),
    ("尽快成交 POV９％", False, False),
])
def test_shared_rule(text, ratio, expected):
    from app.extraction.fast_execution import resolve_fast_execution

    assert resolve_fast_execution(text, has_explicit_pov_ratio=ratio) is expected


@pytest.mark.parametrize("text,ratio,expected", [
    ("最大跟量", None, True),
    ("最大跟量 POV9", "9", True),
    ("尽快成交", None, True),
    ("尽快成交 POV9", "9", False),
    ("普通跟量", None, False),
    ("积极跟量", None, True),
    ("尽量成交", None, True),
    ("快速成交 POV9", "9", False),
    ("尽快成交，平50%", None, True),
])
def test_same_expression_has_same_flag_in_three_products(text, ratio, expected):
    opened = parse_place_params_with_lineage(text, "Q-20260921-0000000001")
    raw_close = f"{ORDER} {text}"
    closed, _ = normalize_place_candidates(
        close_candidates({"orderId": ORDER, "hasFastExecutionIntent": text,
                          "closeOrderPovRatio": ratio}),
        {"raw": raw_close}, parse_reference_message(None, raw_close), [],
    )
    swapped, _ = swap_rows([{
        "hasFastExecutionIntent": cell(text),
        "placeOrderPovPercent": cell(ratio) if ratio is not None else None,
    }], {"raw": text})
    flags = [opened.orders[0]["has_fast_execution_intent"],
             closed.close_order_list[0].has_fast_execution_intent,
             swapped.order_list[0].has_fast_execution_intent]
    assert flags == [expected] * 3
    if ratio is not None:
        assert opened.orders[0]["pov_ratio"] == float(ratio)
        assert closed.close_order_list[0].close_order_pov_ratio == float(ratio)
        assert swapped.order_list[0].place_order_pov_percent == float(ratio)


@pytest.mark.parametrize("raw", ["不要最大跟量", "如果可以就尽快成交", "尽快成交吗"])
def test_open_negation_and_condition_do_not_enable_maximum(raw):
    result = parse_place_params_with_lineage(raw, "Q-20260921-0000000001")
    assert result.orders[0]["has_fast_execution_intent"] is False


def test_explicit_zero_ratio_is_not_treated_as_missing():
    result = parse_place_params_with_lineage("尽快成交 POV0", "Q-20260921-0000000001")
    assert result.orders[0]["has_fast_execution_intent"] is False
    assert result.orders[0]["pov_ratio"] == 0


def test_swap_compares_only_this_orders_ratio_and_expression():
    first, second = "甲证券 最大跟量", "乙证券 尽快成交 POV9"
    params, records = swap_rows([
        {"placeOrderWindCode": cell("甲证券"), "hasFastExecutionIntent": cell("最大跟量")},
        {"placeOrderWindCode": cell("乙证券"), "hasFastExecutionIntent": cell("尽快成交"),
         "placeOrderPovPercent": cell("9")},
    ], {"raw": first + "；" + second})
    assert [r.has_fast_execution_intent for r in params.order_list] == [True, False]
    assert params.order_list[0].place_order_pov_percent is None
    assert params.order_list[1].place_order_pov_percent == 9
    record = records["swap/place_order.orderList.1.hasFastExecutionIntent"]
    assert record.value is False and record.evidence == "尽快成交" and record.locked


@pytest.mark.parametrize("origin,reference", [("quote", None), ("history", "old-message")])
def test_swap_historical_maximum_cannot_enable_current_order(origin, reference):
    key = origin if origin == "quote" else f"{origin}:{reference}"
    params, _ = swap_rows([{
        "hasFastExecutionIntent": cell("最大跟量", origin=origin, reference=reference),
        "placeOrderQuantity": cell("100股"),
    }], {"raw": "买100股", key: "最大跟量"})
    assert params.order_list[0].has_fast_execution_intent is None
    assert params.order_list[0].place_order_quantity == 100


def test_swap_attachment_rows_keep_independent_flags():
    first, second = "file:0:sheet:0:row:2", "file:0:sheet:0:row:3"
    params, _ = swap_rows([
        {"hasFastExecutionIntent": cell("最大跟量", origin="attachment", reference=first)},
        {"hasFastExecutionIntent": cell("尽快成交", origin="attachment", reference=second),
         "placeOrderPovPercent": cell("9", origin="attachment", reference=second)},
    ], {f"attachment:{first}": "最大跟量", f"attachment:{second}": "尽快成交 POV9"})
    assert [r.has_fast_execution_intent for r in params.order_list] == [True, False]


def test_swap_missing_candidate_remains_none():
    params, _ = swap_rows([{}, {"hasFastExecutionIntent": cell("最大跟量")}],
                          {"raw": "第一笔市价；第二笔最大跟量"})
    assert params.order_list[0].has_fast_execution_intent is None
    assert params.order_list[1].has_fast_execution_intent is True


def test_maximum_rule_does_not_overwrite_explicit_order_parameters():
    raw = "最大跟量，TWAP 14:30-14:50，限价10，100万"
    opened = parse_place_params_with_lineage(raw, "Q-20260921-0000000001").orders[0]
    assert opened["has_fast_execution_intent"] is True
    assert (opened["order_type"], opened["limit_price"], opened["twap_start_time"],
            opened["twap_end_time"], opened["notional_amount"]) == (
                "TWAP", 10, "14:30", "14:50", "1000000",
            )


@pytest.mark.parametrize(("text", "expected"), [
    ("ASAP", True), ("尽快 ASAP 执行", True), ("不要 ASAP", False),
    ("not ASAP", False), ("if ready ASAP", False), ("ASAPer", False),
    ("ASAP POV5%", False),
])
def test_asap_uses_fast_intent_without_overriding_negation_or_ratio(text, expected):
    from app.extraction.fast_execution import resolve_fast_execution

    assert resolve_fast_execution(text) is expected
