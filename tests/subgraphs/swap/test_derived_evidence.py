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
