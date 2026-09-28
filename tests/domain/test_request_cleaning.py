"""Java 请求清洗的行为契约；不调用模型或交易接口。"""
from decimal import Decimal

import pytest


def test_invalid_amount_is_omitted_without_changing_other_orders() -> None:
    """脏本金只删除字段，不能默认零、换算或丢掉整笔订单。"""
    from app.domain.request_cleaning import clean_business_request

    original = {"type": "new_inquiry", "orderList": [
        {"stockCode": "茅台", "notionalAmount": "100万", "limitPrice": "10.25"},
        {"stockCode": "比亚迪", "notionalAmount": "1000000", "hasFastExecutionIntent": False},
    ]}
    result = clean_business_request("option", original)
    assert result.payload["orderList"] == [
        {"stockCode": "茅台", "limitPrice": Decimal("10.25")},
        {"stockCode": "比亚迪", "notionalAmount": Decimal("1000000"), "hasFastExecutionIntent": False},
    ]
    assert original["orderList"][0]["notionalAmount"] == "100万"
    assert any(c["path"] == "orderList.0.notionalAmount" and c["action"] == "omit" for c in result.changes)


@pytest.mark.parametrize("value,expected", [
    (True, None), (False, None), ("100万", None), ("100.25", None),
    ("100.0", 100), ("1e3", 1000), (0, 0), (-2, -2),
    (2**63, None), ("NaN", None), (float("inf"), None), ("1,000", None),
])
def test_java_long_accepts_only_lossless_integers(value, expected) -> None:
    """类型容量属于传输兼容；负数与零的业务合法性由 Java 决定。"""
    from app.domain.request_cleaning import clean_business_request

    result = clean_business_request("swap", {"type": "place_order_request", "orderList": [{"placeOrderQuantity": value}]})
    order = result.payload["orderList"][0]
    assert order == ({} if expected is None else {"placeOrderQuantity": expected})


def test_close_numeric_text_and_nulls_are_cleaned() -> None:
    """字符串金额同样过滤单位，合法金额保持字符串；零和 false 不丢失。"""
    from app.domain.request_cleaning import clean_business_request

    result = clean_business_request("close", {"closeOrderList": [
        {"internalTradeId": "OPT-1", "closeOrderNotionalDelta": "100万", "closeOrderPrice": " NULL ", "confirmFullClose": False},
        {"internalTradeId": "OPT-2", "closeOrderNotionalDelta": "100.25", "closeOrderPrice": 0},
    ]}, intent="close_order_request")
    assert result.payload["closeOrderReqVO"]["closeOrderList"] == [
        {"internalTradeId": "OPT-1", "confirmFullClose": False},
        {"internalTradeId": "OPT-2", "closeOrderNotionalDelta": "100.25", "closeOrderPrice": 0},
    ]


@pytest.mark.parametrize("product,expected", [
    ("option", {"type": None, "operate": None, "orderList": []}),
    ("swap", {"type": None, "orderList": []}),
    ("close", {"type": "close_order_request", "closeOrderReqVO": {}, "operate": "", "orderList": [], "optionRfq": {}}),
])
@pytest.mark.parametrize("raw", ["{broken-json", ""])
def test_dify_json_decode_fallback_keeps_branch_wire_shape(product, expected, raw) -> None:
    """对照 Dify 三段原代码：空对象继续提交且不补 unknown_intent。"""
    from app.domain.request_cleaning import clean_business_request

    result = clean_business_request(product, raw, intent="close_order_request")
    assert result.payload == expected
    assert result.json_fallback is True


def test_java_specific_formats_are_not_reinterpreted() -> None:
    """只保留后端明确支持的百分比/期限/时间，不实现换算与日期补齐。"""
    from app.domain.request_cleaning import clean_business_request

    option = clean_business_request("option", {"orderList": [{"strikePercentage": "100%", "povRatio": "10%", "tenor": "1Y"}]})
    assert option.payload["orderList"] == [{"strikePercentage": "100%", "tenor": "1Y"}]
    swap = clean_business_request("swap", {"orderList": [{"placeOrderStartTime": "14:30", "placeOrderEndTime": "明天收盘"}]})
    assert swap.payload["orderList"] == [{"placeOrderStartTime": "14:30"}]


@pytest.mark.parametrize("payload", ["[]", {"orderList": [None]}, {"orderList": [{"orderId": "null"}]}])
def test_valid_json_with_broken_structure_or_identity_is_not_empty_fallback(payload) -> None:
    """JSON 语法容错不能吞掉结构错误或改变目标订单。"""
    from app.domain.request_cleaning import clean_business_request

    with pytest.raises(ValueError):
        clean_business_request("option", payload)


@pytest.mark.parametrize("value", ["9:3", "2026-9-2 09:30", "25:99"])
def test_time_must_match_java_supported_format(value) -> None:
    """Python 的宽松 strptime 不能让 Java 不支持的日期格式漏过清洗。"""
    from app.domain.request_cleaning import clean_business_request

    result = clean_business_request("swap", {"orderList": [{"placeOrderStartTime": value}]})
    assert result.payload["orderList"] == [{}]
