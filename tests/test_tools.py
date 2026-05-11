"""tools/ 单元测试 — 验证 Java DTO 1:1 + 枚举完整性。"""
from __future__ import annotations

from decimal import Decimal

from app.tools import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    GoatsOrderDirection,
    GoatsPriceType,
    GoatsTransactionType,
    OptionIntentionType,
    SwapIntentionType,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
    SecuritiesInstrumentReqVO,
)


# ============================================================
# 枚举完整性（对齐 Java 真实 type 值）
# ============================================================


def test_option_intention_type_has_16_values() -> None:
    """contracts §2.1：StockEnum.stockOptionIntentionType 16 值。"""
    assert len(OptionIntentionType) == 16
    # 关键值存在
    assert OptionIntentionType.NEW_INQUIRY.value == "new_inquiry"
    assert OptionIntentionType.PLACE_ORDER_FROM_QUOTE.value == "place_order_from_quote"
    assert OptionIntentionType.CLOSE_ORDER_REQUEST.value == "close_order_request"
    assert OptionIntentionType.UNKNOWN_INTENT.value == "unknown_intent"


def test_swap_intention_type_has_7_values() -> None:
    """contracts §3.1：SwapEnum.SwapIntentionType 7 值。"""
    assert len(SwapIntentionType) == 7
    assert SwapIntentionType.PLACE_ORDER_REQUEST.value == "place_order_request"
    assert SwapIntentionType.CONFIRM_MODIFY_ORDER.value == "confirm_modify_order"


def test_goats_enums_match_java() -> None:
    """contracts §5：Goats 共用枚举关键值。"""
    assert GoatsOrderDirection.BUY.value == "BUY"
    assert GoatsOrderDirection.SHORT_OPEN.value == "SHORT_OPEN"
    assert GoatsPriceType.LIMIT_ORDER.value == "LimitOrder"
    assert GoatsTransactionType.HK_STOCK.value == "HK_STOCK"


# ============================================================
# Pydantic round-trip（确保字段名严格匹配 Java DTO）
# ============================================================


def test_swap_reqvo_round_trip() -> None:
    """互换下单 ReqVO 的 JSON 序列化必须保留 camelCase。"""
    req = SwapOrderOpenApiSaveReqVO(
        type=SwapIntentionType.PLACE_ORDER_REQUEST,
        orderList=[
            SwapOrderOpenApiBaseSaveReqVO(
                placeOrderWindCode="600036.SH",
                placeOrderTransactionType=GoatsTransactionType.A_SHARE,
                placeOrderQuantity=1000,
                placeOrderQuantityHand=10,
                placeOrderOrderDirection=GoatsOrderDirection.BUY,
                placeOrderPriceType=GoatsPriceType.LIMIT_ORDER,
                placeOrderPrice=Decimal("38.50"),
            )
        ],
        conversationId="c-1",
        messageId=1,
        messageContent="测试",
        rawContent="测试",
        userId="u-1",
        roomId="r-1",
    )
    dumped = req.model_dump(mode="json", exclude_none=True)
    assert dumped["type"] == "place_order_request"
    assert "orderList" in dumped  # 不能漂成 order_list
    assert dumped["orderList"][0]["placeOrderWindCode"] == "600036.SH"
    assert dumped["orderList"][0]["placeOrderQuantityHand"] == 10
    assert dumped["conversationId"] == "c-1"


def test_option_reqvo_round_trip() -> None:
    """期权下单 ReqVO 的 JSON 序列化必须保留 camelCase。"""
    req = FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType.NEW_INQUIRY,
        orderList=[
            FinancialOrderOpenApiBaseSaveReqVO(
                placeOrderWindCode="600519.SH",
                placeOrderQuantity=100,
                placeOrderOrderDirection=GoatsOrderDirection.BUY,
                placeOrderPriceType=GoatsPriceType.MARKET_ORDER,
                notionalAmount=Decimal("100000.00"),
            )
        ],
        conversationId="c-1",
        messageId=1,
        messageContent="测试期权",
        rawContent="测试期权",
        userId="u-1",
        roomId="r-1",
    )
    dumped = req.model_dump(mode="json", exclude_none=True)
    assert dumped["type"] == "new_inquiry"
    assert dumped["orderList"][0]["placeOrderWindCode"] == "600519.SH"
    assert dumped["orderList"][0]["notionalAmount"] == "100000.00"


def test_ticker_reqvo_keyword_items() -> None:
    """标的查询的关键词列表 schema。"""
    req = SecuritiesInstrumentReqVO(
        keywordItems=[
            {"keyword": "招行", "isFull": False},  # type: ignore[list-item]
            {"keyword": "600036.SH", "isFull": True},  # type: ignore[list-item]
        ]
    )
    dumped = req.model_dump(mode="json", exclude_none=True)
    assert dumped["keywordItems"][0]["keyword"] == "招行"
    assert dumped["keywordItems"][1]["isFull"] is True
