"""Rules moved out of swap prompts: exact units, enums, proportions and time."""
import importlib

import pytest


@pytest.mark.parametrize("field,value,expected", [
    ("placeOrderQuantity", "8.45万股", 84500),
    ("placeOrderQuantity", "2.5千股", 2500),
    ("placeOrderQuantity", "100万手", 1000000),
    ("placeOrderQuantity", "2lot", 2),
    ("placeOrderQuantity", "55,200股", 55200),
    ("placeOrderNotional", "1.5555万元", 15555),
    ("placeOrderNotional", "两千万", 20000000),
    ("placeOrderQuantityUnit", "2lot", "HAND"),
    ("placeOrderQuantityUnit", "8.45万股", "SHARE"),
    ("placeOrderQuantityUnit", "1877w人民币", "AMOUNT"),
    ("placeOrderOrderDirection", "賣出", "SELL"),
    ("placeOrderOrderDirection", "平空", "SHORT_CLOSE"),
    ("placeOrderPriceType", "不限价", "MarketOrder"),
    ("placeOrderAlgorithmType", "全天均价", "TWAP"),
    ("placeOrderNotionalCurrency", "港元", "HKD"),
    ("placeOrderEntrustRatio", "平三成", .3),
    ("placeOrderEntrustRatio", "平三分之一", .3333),
    ("placeOrderEntrustRatio", "全部平空", 1.0),
    ("placeOrderStartTime", "9:05", "09:05"),
    ("placeOrderRelativeTimeMinutes", "半小时", 30),
])
def test_swap_deterministic_field_rules(field, value, expected):
    module = importlib.import_module("app.subgraphs.swap.normalize")
    assert module.normalize_field(field, value) == expected


@pytest.mark.parametrize("field,value", [
    ("placeOrderQuantity", "1.5股"),
    ("placeOrderQuantity", "-10股"),
    ("placeOrderEntrustRatio", "平125%"),
    ("placeOrderStartTime", "25:00"),
    ("placeOrderPrice", "unknown"),
])
def test_invalid_values_are_not_silently_repaired(field, value):
    module = importlib.import_module("app.subgraphs.swap.normalize")
    with pytest.raises(ValueError):
        module.normalize_field(field, value)


def test_pov_percentage_is_not_a_close_ratio():
    module = importlib.import_module("app.subgraphs.swap.normalize")
    assert module.normalize_field("placeOrderEntrustRatio", "50%", "跟量50%") is None


@pytest.mark.parametrize("field,value,expected", [
    ("placeOrderPremarket", "盘前", True),
    ("placeOrderPremarket", "非盘前", False),
    ("placeOrderCloseIntent", "平空", True),
    ("hasFastExecutionIntent", "尽快", True),
    ("hasFastExecutionIntent", "不要尽快", False),
])
def test_boolean_fields_need_their_own_semantic_signal(field, value, expected):
    module = importlib.import_module("app.subgraphs.swap.normalize")
    assert module.normalize_field(field, value) is expected


@pytest.mark.parametrize("field", ["placeOrderPremarket", "placeOrderCloseIntent", "hasFastExecutionIntent"])
def test_unrelated_text_cannot_become_true(field):
    module = importlib.import_module("app.subgraphs.swap.normalize")
    with pytest.raises(ValueError):
        module.normalize_field(field, "某个账户")


def test_price_type_is_derived_from_explicit_price_with_record():
    from app.extraction.candidates import candidate_model
    from app.subgraphs.swap.models import SwapPlaceOrderParams
    from app.subgraphs.swap.normalize import normalize_candidates

    output = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderPrice": {"value": "24.6", "evidence": "24.6", "confidence": .99},
    }]})
    params, records = normalize_candidates(output, {"raw": "24.6"})
    assert params.order_list[0].place_order_price_type == "LimitOrder"
    record = records["swap/place_order.orderList.0.placeOrderPriceType"]
    assert record.source == "inferred" and record.evidence == "24.6" and record.locked


def test_average_price_is_normalized_by_code():
    from app.subgraphs.swap.normalize import normalize_field
    assert normalize_field("placeOrderAlgorithmType", "均价") == "TWAP"


def test_instrument_code_case_is_formatting_only():
    from app.subgraphs.swap.normalize import normalize_field
    assert normalize_field("placeOrderWindCode", "300748.sz") == "300748.SZ"
    assert normalize_field("placeOrderWindCode", "unknown") == "unknown"
