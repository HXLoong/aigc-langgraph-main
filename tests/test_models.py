"""子图的 Pydantic 模型测试。

只测不依赖 LLM 的部分：
- 模型字段校验
- 枚举约束
- 参数限制检查节点的纯 Python 逻辑
"""
from __future__ import annotations

import importlib.util

import pytest
from pydantic import ValidationError

from app.subgraphs.close_models import (
    CloseIntentOutput,
    CloseOrderNoListOutput,
)
from app.subgraphs.option_models import (
    OptionOrderLeg,
    OptionParamLimit,
)
from app.subgraphs.swap_models import (
    SwapIntentOutput,
    SwapOrderIdOutput,
    SwapOrderLeg,
    SwapPlaceOrderOutput,
)


# ============================================================
# SwapIntentOutput
# ============================================================
def test_swap_intent_valid():
    o = SwapIntentOutput(type="place_order_request", confidence=0.9, reason="测试")
    assert o.type == "place_order_request"


def test_swap_intent_invalid_type():
    with pytest.raises(ValidationError):
        SwapIntentOutput(type="invalid_intent")


def test_swap_intent_confidence_bounds():
    with pytest.raises(ValidationError):
        SwapIntentOutput(type="place_order_request", confidence=1.5)


# ============================================================
# SwapOrderLeg
# ============================================================
def test_swap_order_leg_minimum():
    leg = SwapOrderLeg(
        stock_code="600519.SH",
        direction="buy",
        quantity=1000,
    )
    assert leg.price_type == "market"
    assert leg.participation_rate is None


def test_swap_order_leg_participation_rate_bounds():
    # 参与率值域 0~100（与 Dify placeOrderPovPercent 的百分比一致）
    with pytest.raises(ValidationError):
        SwapOrderLeg(
            stock_code="600519.SH",
            direction="buy",
            quantity=100,
            participation_rate=150.0,
        )


def test_swap_order_leg_quantity_positive():
    with pytest.raises(ValidationError):
        SwapOrderLeg(stock_code="600519.SH", direction="buy", quantity=0)


# ============================================================
# SwapPlaceOrderOutput
# ============================================================
def test_swap_place_order_requires_at_least_one_leg():
    with pytest.raises(ValidationError):
        SwapPlaceOrderOutput(order_list=[])


def test_swap_place_order_valid():
    out = SwapPlaceOrderOutput(order_list=[
        SwapOrderLeg(stock_code="600519.SH", direction="buy", quantity=1000),
    ])
    assert len(out.order_list) == 1
    assert out.type == "place_order_request"


# ============================================================
# Dify camelCase alias 兼容（LLM 按原提示词输出时走这里）
# ============================================================
def test_swap_order_leg_accepts_dify_camelcase():
    """验证 LLM 按 Dify prompt 输出的 camelCase JSON 能被 Pydantic 正确解析。"""
    leg = SwapOrderLeg.model_validate({
        "placeOrderWindCode": "0700.HK",
        "placeOrderOrderDirection": "BUY",
        "placeOrderQuantity": 2000,
        "placeOrderPriceType": "LimitOrder",
        "placeOrderPrice": 320,
        "placeOrderAlgorithmType": "POV",
        "placeOrderPovPercent": 25,
        "placeOrderShortname": "ACCOUNT_L",
        "placeOrderTransactionType": "HK_STOCK",
        "orderId": None,
    })
    # 归一化：BUY → buy，LimitOrder → limit
    assert leg.direction == "buy"
    assert leg.price_type == "limit"
    # alias 字段命名映射
    assert leg.stock_code == "0700.HK"
    assert leg.quantity == 2000
    assert leg.limit_price == 320
    assert leg.counterparty_name == "ACCOUNT_L"
    assert leg.transaction_type == "HK_STOCK"


def test_swap_place_order_accepts_dify_camelcase_orderlist():
    """LLM 输出顶层 orderList（camelCase）也能被解析为 order_list。"""
    out = SwapPlaceOrderOutput.model_validate({
        "type": "place_order_request",
        "orderList": [
            {
                "placeOrderWindCode": "600519.SH",
                "placeOrderOrderDirection": "SELL",
                "placeOrderQuantity": 500,
                "placeOrderPriceType": "MarketOrder",
            }
        ],
    })
    assert out.type == "place_order_request"
    assert len(out.order_list) == 1
    assert out.order_list[0].stock_code == "600519.SH"
    assert out.order_list[0].direction == "sell"
    assert out.order_list[0].price_type == "market"


def test_swap_order_leg_extra_fields_ignored():
    """Dify 原提示词里的字段比 Pydantic 覆盖的多，多余字段应被安全忽略。"""
    leg = SwapOrderLeg.model_validate({
        "placeOrderWindCode": "000001.SZ",
        "placeOrderOrderDirection": "buy",
        "placeOrderQuantity": 100,
        "unknownFutureField": "任何未来字段",  # 不认识的字段 → extra="ignore" 丢弃
    })
    assert leg.stock_code == "000001.SZ"
    # 没有抛 ValidationError 就说明 extra=ignore 生效


# ============================================================
# SwapOrderIdOutput
# ============================================================
def test_swap_order_id_format():
    o = SwapOrderIdOutput(order_id="H-20260304-ABCD123456")
    assert o.order_id == "H-20260304-ABCD123456"


def test_swap_order_id_invalid_format():
    # 小写字母应被拒
    with pytest.raises(ValidationError):
        SwapOrderIdOutput(order_id="h-20260304-ABCD123456")
    # 缺少前缀
    with pytest.raises(ValidationError):
        SwapOrderIdOutput(order_id="20260304-ABCD123456")
    # 日期位数不对
    with pytest.raises(ValidationError):
        SwapOrderIdOutput(order_id="H-2026304-ABCD123456")


# ============================================================
# OptionParamLimit
# ============================================================
def test_option_param_limit_within():
    limit = OptionParamLimit(
        stock_count=3, strike_count=2, tenor_count=1,
        combo_count=6, exceeded=False,
    )
    assert not limit.exceeded


def test_option_param_limit_exceeded_combo():
    # 3×3×2 = 18 > 10
    limit = OptionParamLimit(
        stock_count=3, strike_count=3, tenor_count=2,
        combo_count=18, exceeded=True, reason="组合数 18 > 10",
    )
    assert limit.exceeded


# ============================================================
# OptionOrderLeg
# ============================================================
def test_option_order_leg_default_option_type():
    leg = OptionOrderLeg(stock_code="600519.SH")
    assert leg.option_type == "欧式看涨"
    assert leg.direction == "buy"


def test_option_order_leg_valid_option_type():
    leg = OptionOrderLeg(stock_code="600519.SH", option_type="雪球")
    assert leg.option_type == "雪球"


def test_option_order_leg_invalid_option_type():
    with pytest.raises(ValidationError):
        OptionOrderLeg(stock_code="600519.SH", option_type="不存在的期权")


# ============================================================
# CloseIntentOutput
# ============================================================
def test_close_intent_all_types():
    for t in (
        "close_order_query", "close_order_request", "close_order_confirm",
        "close_order_cancel", "close_order_confirm_cancel",
        "close_order_query_status", "unknown",
    ):
        CloseIntentOutput(type=t)


def test_close_order_no_list_empty_default():
    o = CloseOrderNoListOutput()
    assert o.order_no_list == []


# ============================================================
# 路由函数测试（来自 swap/option/close 子图）
# 需要安装 langgraph；未安装时仅跳过这三个测试，不影响上面的模型测试
# ============================================================
_langgraph_available = importlib.util.find_spec("langgraph") is not None


@pytest.mark.skipif(not _langgraph_available, reason="需要安装 langgraph 依赖")
def test_swap_route_by_intent():
    from app.subgraphs.swap import route_by_intent

    assert route_by_intent({"intent": "place_order_request"}) == "extract_place_order"
    assert route_by_intent({"intent": "confirm_order"}) == "extract_order_id"
    assert route_by_intent({"intent": "cancel_order_request"}) == "extract_order_id"
    assert route_by_intent({"intent": "unknown"}) == "call_api"


@pytest.mark.skipif(not _langgraph_available, reason="需要安装 langgraph 依赖")
def test_close_route_by_intent():
    from app.subgraphs.close import route_close_intent

    assert route_close_intent({"intent": "close_order_query"}) == "extract_holding_query"
    assert route_close_intent({"intent": "close_order_request"}) == "extract_place_close"
    assert route_close_intent({"intent": "close_order_confirm"}) == "extract_order_no_list"
    assert route_close_intent({"intent": "close_order_cancel"}) == "extract_order_no_list"


@pytest.mark.skipif(not _langgraph_available, reason="需要安装 langgraph 依赖")
def test_option_quick_query_keywords():
    from app.subgraphs.option import QUICK_QUERY_KEYWORDS

    assert "雪球" in QUICK_QUERY_KEYWORDS
    assert "参与型看涨" in QUICK_QUERY_KEYWORDS
