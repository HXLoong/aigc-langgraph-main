"""真实模型基线暴露的原文候选归一化缺口，保留证据与数值边界。"""
import pytest

from app.extraction.candidates import candidate_model
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates, normalize_field


def _candidates(values):
    return candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        key: {"value": value, "evidence": value, "confidence": 1, "origin": "raw"}
        for key, value in values.items()
    }]})


def test_explicit_buy_open_keeps_quantity_and_original_evidence():
    raw = "买入开仓 000993 神火股份 64万股 POV10%市价 聚鸣价值精选"
    candidates = _candidates({
        "placeOrderWindCode": "000993 神火股份",
        "placeOrderQuantity": "64万股",
        "placeOrderOrderDirection": "买入开仓",
        "placeOrderPriceType": "市价",
        "placeOrderPovPercent": "10%",
    })
    params, records = normalize_candidates(candidates, {"raw": raw})
    order = params.order_list[0]
    assert order.place_order_order_direction == "BUY"
    assert order.place_order_quantity == 640000
    assert order.place_order_wind_code == "000993 神火股份"
    assert records["swap/place_order.orderList.0.placeOrderOrderDirection"].evidence == "买入开仓"


@pytest.mark.parametrize("value", ["POV1%", "pov 1%", "POV：1%"])
def test_pov_label_in_raw_percentage_is_normalized_without_losing_evidence(value):
    raw = f"600487 亨通光电，买入，315万股，MKT，{value} 聚鸣价值精选"
    candidates = _candidates({
        "placeOrderQuantity": "315万股", "placeOrderPovPercent": value,
        "placeOrderPriceType": "MKT", "placeOrderOrderDirection": "买入",
    })
    params, records = normalize_candidates(candidates, {"raw": raw})
    assert params.order_list[0].place_order_pov_percent == 1
    assert params.order_list[0].place_order_quantity == 3150000
    assert records["swap/place_order.orderList.0.placeOrderPovPercent"].evidence == value


@pytest.mark.parametrize("value", ["POV0%", "POV-1%", "POV101%", "POV10%限价5", "POV1%/2%"])
def test_pov_prefix_does_not_bypass_bounds_or_accept_multiple_values(value):
    with pytest.raises(ValueError):
        normalize_field("placeOrderPovPercent", value)


@pytest.mark.parametrize("value", ["不要买入开仓", "买入开仓或卖出", "买入开仓卖出平仓"])
def test_buy_open_alias_does_not_accept_negated_or_mixed_actions(value):
    with pytest.raises(ValueError):
        normalize_field("placeOrderOrderDirection", value)
