"""派生单位/币种沿用原字段来源，附件与引用不能变成本轮原文。"""
import pytest

from app.extraction.candidates import candidate_model
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates


@pytest.mark.parametrize("origin,reference,key", [
    ("attachment", "sheet:0:row:2", "attachment:sheet:0:row:2"),
    ("quote", None, "quote"),
])
def test_derived_money_keeps_evidence_origin(origin, reference, key):
    candidate = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderQuantity": {"value": "200万港币", "evidence": "200万港币",
                               "origin": origin, "reference": reference, "confidence": .95},
    }]})
    params, records = normalize_candidates(candidate, {key: "买入200万港币"})
    assert params.order_list[0].place_order_notional == 2000000
    for name in ("placeOrderQuantityUnit", "placeOrderNotional", "placeOrderNotionalCurrency"):
        record = records["swap/place_order.orderList.0." + name]
        assert record.origin == key
        assert record.confidence == .95
        assert record.source == "inferred"
        assert record.locked


def test_attachment_at_price_expression_is_quantity_not_notional():
    candidate = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderQuantity": {"value": "100w", "evidence": "100w@20", "origin": "attachment",
                               "reference": "row:1", "confidence": 1},
    }]})
    params, _ = normalize_candidates(candidate, {"attachment:row:1": "100w@20"})
    assert params.order_list[0].place_order_quantity == 1000000
    assert params.order_list[0].place_order_quantity_unit == "SHARE"
    assert params.order_list[0].place_order_notional is None


@pytest.mark.parametrize("unit,quantity,notional", [("万股", 25000, None), ("万元", None, 25000)])
def test_separate_quantity_and_scale_are_combined_by_code(unit, quantity, notional):
    payload = {"orderList": [{
        "placeOrderQuantity": {"value": "2.5", "evidence": "数量:2.5", "origin": "attachment",
                               "reference": "r1", "confidence": .9},
        "placeOrderQuantityUnit": {"value": unit, "evidence": unit, "origin": "attachment",
                                   "reference": "header", "confidence": .95},
    }]}
    params, records = normalize_candidates(candidate_model(SwapPlaceOrderParams).model_validate(payload),
                                          {"attachment:r1": "数量:2.5", "attachment:header": unit})
    assert params.order_list[0].place_order_quantity == quantity
    assert params.order_list[0].place_order_notional == notional
    prefix = "swap/place_order.orderList.0."
    field = "placeOrderNotional" if notional is not None else "placeOrderQuantity"
    assert records[prefix + field].derived_from == [prefix + "placeOrderQuantity.candidate", prefix + "placeOrderQuantityUnit.candidate"]
    assert records[prefix + field].origin == "attachment:r1"


def test_inline_quantity_unit_cannot_conflict_with_explicit_unit():
    payload = {"orderList": [{
        "placeOrderQuantity": {"value": "2万股", "evidence": "2万股", "confidence": 1},
        "placeOrderQuantityUnit": {"value": "手", "evidence": "手", "confidence": 1},
    }]}
    with pytest.raises(ValueError, match="单位"):
        normalize_candidates(candidate_model(SwapPlaceOrderParams).model_validate(payload),
                             {"raw": "2万股 手"})
