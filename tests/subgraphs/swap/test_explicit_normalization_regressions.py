"""公网失败原文的确定性别名；混合动作和未定执行窗口仍需澄清。"""
from __future__ import annotations

import pytest

from app.extraction.candidates import candidate_model
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates, normalize_field


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("沽", "SELL"), ("沽出", "SELL"), ("全卖出", "SELL"),
        ("卖出全部", "SELL"), ("全部卖掉", "SELL"), ("清仓卖出", "SELL"),
        ("全部卖出", "SELL"), ("全部賣出", "SELL"),
        ("賣出平倉", "SELL"), ("卖平", "SELL"), ("多头平仓", "SELL"),
        ("卖开", "SHORT_OPEN"), ("卖出开仓", "SHORT_OPEN"),
        ("賣出開倉", "SHORT_OPEN"), ("沽空", "SHORT_OPEN"),
        ("买平", "SHORT_CLOSE"), ("買平", "SHORT_CLOSE"),
        ("空头平仓", "SHORT_CLOSE"), ("买开", "BUY"),
        ("買入開倉", "BUY"), ("买入全部", "BUY"),
    ],
)
def test_explicit_direction_aliases(value: str, expected: str) -> None:
    assert normalize_field("placeOrderOrderDirection", value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("市价单", "MarketOrder"), ("市價單", "MarketOrder"),
     ("市价委托", "MarketOrder"), ("限价单", "LimitOrder"), ("限價單", "LimitOrder")],
)
def test_explicit_order_price_type_aliases(value: str, expected: str) -> None:
    assert normalize_field("placeOrderPriceType", value) == expected


@pytest.mark.parametrize("field", ["placeOrderPovPercent", "placeOrderTotalPovPercent"])
@pytest.mark.parametrize("value", ["跟10%", "跟量 10%", "占10%", "占比10%", "POV跟量10%"])
def test_participation_label_retains_numeric_bounds(field: str, value: str) -> None:
    assert normalize_field(field, value) == 10


@pytest.mark.parametrize("value", ["3个亿", "3個億", "2.1个亿"])
def test_explicit_large_amount_classifier(value: str) -> None:
    expected = 210000000 if value.startswith("2.1") else 300000000
    assert normalize_field("placeOrderNotional", value) == expected


def test_candidate_aliases_preserve_original_evidence_and_record_source() -> None:
    raw = "沽出0700.HK 22000股 市价单 占5%"
    values = {
        "placeOrderWindCode": "0700.HK", "placeOrderOrderDirection": "沽出",
        "placeOrderQuantity": "22000股", "placeOrderPriceType": "市价单",
        "placeOrderPovPercent": "占5%",
    }
    candidates = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        field: {"value": value, "evidence": value, "confidence": .95}
        for field, value in values.items()
    }]})
    params, records = normalize_candidates(candidates, {"raw": raw})
    order = params.order_list[0]
    assert order.place_order_order_direction == "SELL"
    assert order.place_order_price_type == "MarketOrder"
    assert order.place_order_quantity == 22000
    assert order.place_order_pov_percent == 5
    for field, value in values.items():
        record = records["swap/place_order.orderList.0." + field]
        assert record.evidence == value
        assert record.origin == "raw"
        assert record.source == "user"


@pytest.mark.parametrize(
    "value",
    ["不要沽出", "沽出或买入", "卖开买平", "买入卖出", "清仓", "平仓", "减仓", "全减",
     "暫買", "已買", "暂沽", "暂入"],
)
def test_direction_remains_ambiguous_or_conflicting(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_field("placeOrderOrderDirection", value)


@pytest.mark.parametrize("value", ["跟0%", "占-1%", "跟量101%", "占10%/20%", "不要跟10%", "跟1,2%", "占1，2%", "占1 2%"])
def test_participation_labels_cannot_hide_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_field("placeOrderPovPercent", value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("placeOrderPriceType", "全天均价"), ("placeOrderAlgorithmType", "稳健"),
        ("placeOrderAlgorithmType", "ASAP"), ("placeOrderTransactionType", "互换"),
        ("placeOrderQuantity", "-34250"), ("placeOrderNotional", "约2.1个亿"),
        ("placeOrderNotional", "3个亿或4个亿"), ("placeOrderNotional", "2.1个亿左右"),
        ("placeOrderEndTime", "到收盘"), ("placeOrderRelativeTimeMinutes", "全天"),
        ("placeOrderCloseIntent", "全部持仓"),
    ],
)
def test_candidate_contract_errors_and_ambiguous_values_are_not_silently_fixed(
    field: str, value: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_field(field, value)


@pytest.mark.parametrize("value", ["3个亿", "3個億"])
def test_large_amount_candidate_retains_amount_unit(value: str) -> None:
    candidates = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderQuantity": {"value": value, "evidence": value, "confidence": .95},
    }]})
    params, records = normalize_candidates(candidates, {"raw": value})
    order = params.order_list[0]
    assert order.place_order_quantity is None
    assert order.place_order_notional == 300000000
    assert order.place_order_quantity_unit == "AMOUNT"
    assert records["swap/place_order.orderList.0.placeOrderNotional"].evidence == value


@pytest.mark.parametrize("direction", ["沽出", "多头平仓", "空头平仓"])
def test_new_direction_alias_cannot_be_bypassed_by_later_letter(direction: str) -> None:
    with pytest.raises(ValueError):
        normalize_field("placeOrderOrderDirection", "B", f"{direction}100股 B")


@pytest.mark.parametrize("value", ["全部卖掉", "全部卖出", "全部賣出", "卖出全部", "全卖出"])
def test_sell_all_phrase_is_explicit_close_intent(value: str) -> None:
    assert normalize_field("placeOrderCloseIntent", value) is True


@pytest.mark.parametrize("value", ["不要全部卖掉", "不需要全卖出"])
def test_negated_sell_all_does_not_become_close_intent(value: str) -> None:
    assert normalize_field("placeOrderCloseIntent", value) is False


@pytest.mark.parametrize("value", ["全部卖掉或买入", "买入全部", "全部", "剩余全部持仓"])
def test_sell_all_requires_the_complete_unambiguous_phrase(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_field("placeOrderCloseIntent", value)


@pytest.mark.parametrize("field", ["placeOrderOrderDirection", "placeOrderCloseIntent"])
@pytest.mark.parametrize("value", ["如果全部卖出", "价格达到10再全部卖出", "全部卖出或只卖一半"])
def test_conditional_or_alternative_sell_all_is_not_an_unconditional_action(
    field: str, value: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_field(field, value)
