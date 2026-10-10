"""共用 Pydantic 模型 + Goats 枚举（对齐真实 Java DTO/Enum）。

字段命名保留 Java camelCase 便于一一对照。引用源：
- `SwapEnum.java`   · 互换枚举
- `StockEnum.java`  · 期权 / 平仓枚举
- `*ReqVO.java`     · 入参 DTO
- `*RespVO.java`    · 出参 DTO
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ============================================================
# Goats 共用枚举（SwapEnum.java）
# ============================================================


class GoatsTransactionType(str, Enum):
    """交易品种（SwapEnum.java:59）。"""

    A_SHARE = "A_SHARE"
    HK_STOCK = "HK_STOCK"
    US_STOCK = "US_STOCK"
    SZ_HK_CONNECT = "SZ_HK_CONNECT"
    SH_HK_CONNECT = "SH_HK_CONNECT"
    CHN_FUTURE = "CHN_FUTURE"
    CROSS_FUTURE = "CROSS_FUTURE"


class GoatsOrderDirection(str, Enum):
    """委托方向（SwapEnum.java:148）。"""

    BUY = "BUY"
    SELL = "SELL"
    SHORT_OPEN = "SHORT_OPEN"
    SHORT_CLOSE = "SHORT_CLOSE"


class GoatsPriceType(str, Enum):
    """价格类型（SwapEnum.java:182）。注意 code 是 PascalCase。"""

    LIMIT_ORDER = "LimitOrder"
    MARKET_ORDER = "MarketOrder"


class GoatsAlgoType(str, Enum):
    """算法类型（SwapEnum.java:213）。"""

    POV = "POV"
    TWAP = "TWAP"
    VWAP = "VWAP"
    ICEBERG = "ICEBERG"
    SNIPER = "SNIPER"


# ============================================================
# 意图枚举（SwapEnum / StockEnum）
# ============================================================


class SwapIntentionType(str, Enum):
    """互换意图（SwapEnum.SwapIntentionType，7 值）。"""

    PLACE_ORDER_REQUEST = "place_order_request"
    CONFIRM_ORDER = "confirm_order"
    CANCEL_ORDER_REQUEST = "cancel_order_request"
    CONFIRM_CANCEL_ORDER = "confirm_cancel_order"
    CONFIRM_MODIFY_ORDER = "confirm_modify_order"
    QUERY_ORDER_STATUS = "query_order_status"
    UNKNOWN_INTENT = "unknown_intent"


class StockOptionIntentionType(str, Enum):
    """期权意图（StockEnum.stockOptionIntentionType，16 值）。"""

    NEW_INQUIRY = "new_inquiry"
    PLACE_ORDER_FROM_QUOTE = "place_order_from_quote"
    CONFIRM_ORDER = "confirm_order"
    CANCEL_ORDER_REQUEST = "cancel_order_request"
    REQUEST_CANCEL_ORDER = "request_cancel_order"
    CONFIRM_CANCEL_ORDER = "confirm_cancel_order"
    REQUEST_MODIFY_ORDER = "request_modify_order"
    CONFIRM_MODIFY_ORDER = "confirm_modify_order"
    QUERY_ORDER_STATUS = "query_order_status"
    CLOSE_ORDER_QUERY = "close_order_query"
    CLOSE_ORDER_REQUEST = "close_order_request"
    CLOSE_ORDER_CONFIRM = "close_order_confirm"
    CLOSE_ORDER_CANCEL_REQUEST = "close_order_cancel_request"
    CLOSE_ORDER_CANCEL_CONFIRM = "close_order_cancel_confirm"
    CLOSE_ORDER_ORDER_QUERY = "close_order_order_query"
    UNKNOWN_INTENT = "unknown_intent"


# ============================================================
# 关键词查询项（KeywordItem.java）
# ============================================================


class KeywordItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    keyword: str
    isFull: bool = False


# ============================================================
# 互换 ReqVO / 子结构（SwapOrderOpenApiBaseSaveReqVO.java）
# ============================================================


class SwapOrderItem(BaseModel):
    """对齐 `SwapOrderOpenApiBaseSaveReqVO`（互换订单子项）。"""

    model_config = ConfigDict(extra="allow")

    orderId: str | None = None
    placeOrderUltraContractCode: str | None = None
    placeOrderWindCode: str | None = None
    placeOrderWindCodeList: list[KeywordItem] | None = None
    placeOrderTransactionType: GoatsTransactionType | None = None
    placeOrderQuantity: int | None = None
    placeOrderQuantityHand: int | None = None
    placeOrderOrderDirection: GoatsOrderDirection | None = None
    placeOrderPriceType: GoatsPriceType | None = None
    placeOrderOrderType: str | None = None
    placeOrderAlgorithmType: GoatsAlgoType | None = None
    placeOrderPrice: Decimal | None = None
    placeOrderPovPercent: Decimal | None = None
    placeOrderDisplayQty: int | None = None
    placeOrderMaxVol: Decimal | None = None
    placeOrderPremarket: bool | None = None
    placeOrderStartTime: str | None = None  # 后端宽容多种格式，先用 str
    placeOrderEndTime: str | None = None
    placeOrderShortname: str | None = None
    transactionTypeList: list[str] | None = None


class SwapOperateReqVO(BaseModel):
    """对齐 `SwapOrderOpenApiSaveReqVO`（POST /admin-api/swap-order/operate）。"""

    model_config = ConfigDict(extra="allow")

    type: SwapIntentionType = Field(..., description="意图，必填")
    orderList: list[SwapOrderItem] = Field(default_factory=list)

    # 机器人上下文
    conversationId: str | None = Field(None, description="dify会话id")
    messageId: int = Field(..., description="消息ID（必填）")
    messageContent: str = Field(..., min_length=1, description="消息内容（必填）")
    rawContent: str = Field(..., min_length=1, description="原始消息内容（必填）")
    quoteContent: str | None = None
    quoteAppinfo: str | None = None
    userId: str = Field(..., min_length=1, description="客户ID（必填）")
    roomId: str = Field(..., min_length=1, description="群ID（必填）")
    guid: str | None = None


class SwapConversationOrderReqVO(BaseModel):
    model_config = ConfigDict(extra="ignore")
    conversationId: str = Field(..., min_length=1)


# ============================================================
# 期权 ReqVO / 子结构（FinancialOrderOpenApiBaseSaveReqVO.java）
# ============================================================


class FinancialOrderItem(BaseModel):
    """对齐 `FinancialOrderOpenApiBaseSaveReqVO`（期权订单子项）。"""

    model_config = ConfigDict(extra="allow")

    id: int | None = None
    isValid: int | None = None
    invalidReason: str | None = None
    orderId: str | None = None

    # 标的
    stockCode: str | None = None
    stockName: str | None = None
    stockCodeList: list[KeywordItem] | None = None

    # 期权类型 / 期限
    optionType: str | None = None
    productType: str | None = None
    tenor: str | None = None

    # 欧式看涨
    premiumRatePct: Decimal | None = None
    strikePercentage: Decimal | None = None

    # 参与型
    participationRate: Decimal | None = None

    # 雪球
    snowballKnockOutUpperBarrierPct: Decimal | None = None
    snowballKnockInLowerBarrierPct: Decimal | None = None
    snowballTenorMonths: int | None = None
    snowballMarginPercentagePct: Decimal | None = None
    snowballLockInPeriodMonths: int | None = None
    snowballAnnualizedCouponRatePct: Decimal | None = None
    snowballAbsoluteCouponRatePct: Decimal | None = None
    snowballFeaturesText: str | None = None

    # 建仓指令
    initialOrderInstruction: str | None = None
    orderType: str | None = None  # LIMIT_PRICE / MARKET_PRICE / POV / TWAP
    limitPrice: Decimal | None = None
    notionalAmount: Decimal | None = None
    povRatio: Decimal | None = None
    twapStartTime: str | None = None
    twapEndTime: str | None = None
    shortName: str | None = None

    # 快速询价
    quickInquiryOrderId: int | None = None
    counterpartyList: list[str] | None = None


class CloseOrderItem(BaseModel):
    """平仓单项（对齐 `CloseOrderItemReqVO`，常见字段）。"""

    model_config = ConfigDict(extra="allow")

    orderId: str | None = None
    internalTradeId: str | None = None
    closeOrderNotionalDelta: Decimal | None = None
    closeOrderType: str | None = None
    closeOrderPrice: Decimal | None = None
    closeOrderPovRatio: Decimal | None = None
    closeOrderAlgoStartTime: str | None = None
    closeOrderAlgoEndTime: str | None = None
    hasFastExecutionIntent: bool | None = None
    confirmFullClose: bool | None = None
    stockCode: str | None = None
    stockName: str | None = None


class ContractQueryReqVO(BaseModel):
    model_config = ConfigDict(extra="allow")
    pageNum: int | None = 1
    pageSize: int | None = 100


class CloseOrderReqVO(BaseModel):
    """对齐 `CloseOrderReqVO`（平仓 sub-VO）。"""

    model_config = ConfigDict(extra="allow")

    contractQuery: ContractQueryReqVO | None = None
    closeOrderList: list[CloseOrderItem] | None = None
    confirmOrderNoList: list[str] | None = None
    tradeDate: str | None = None
    queryOrderNoList: list[str] | None = None
    cancelOrderNoList: list[str] | None = None
    confirmCancelOrderNoList: list[str] | None = None


class GoatsOptionRfqReqVO(BaseModel):
    """期权询价/雪球存量参数。"""

    model_config = ConfigDict(extra="allow")

    chatType: str | None = None
    chatInstrument: str | None = None
    productType: str | None = None
    tenor: list[str] | None = None
    strike: list[str] | None = None
    knockInPrice: list[str] | None = None
    knockOutPrice: list[str] | None = None
    estimateMargin: list[str] | None = None


class FinancialOperateReqVO(BaseModel):
    """对齐 `FinancialOrderOpenApiSaveReqVO`（POST /admin-api/financial-orders/operate）。"""

    model_config = ConfigDict(extra="allow")

    operate: str | None = None
    type: StockOptionIntentionType = Field(..., description="意图，必填")
    orderList: list[FinancialOrderItem] = Field(default_factory=list)
    closeOrderReqVO: CloseOrderReqVO | None = None
    optionRfq: GoatsOptionRfqReqVO | None = None

    # 机器人上下文
    conversationId: str | None = None
    messageId: int = Field(..., description="消息ID（必填）")
    messageContent: str = Field(..., min_length=1)
    rawContent: str = Field(..., min_length=1)
    quoteContent: str | None = None
    quoteAppinfo: str | None = None
    userId: str = Field(..., min_length=1)
    roomId: str = Field(..., min_length=1)
    guid: str | None = None


class QueryCloseOrdersReqVO(BaseModel):
    """对齐 `QueryCloseOrdersReqVO`（POST /admin-api/financial-orders/query-close-orders）。"""

    model_config = ConfigDict(extra="ignore")

    orderIds: list[str] | None = Field(default=None, max_length=50)
    contractCodes: list[str] | None = Field(default=None, max_length=20)
    roomId: str | None = None
    messageId: int | None = None


# ============================================================
# 标的 / 交易对手 ReqVO（CounterpartyInfoRespVO 等）
# ============================================================


class SecuritiesInstrumentReqVO(BaseModel):
    model_config = ConfigDict(extra="allow")
    keywordItems: list[KeywordItem] = Field(default_factory=list)


class CounterpartyInfoReqVO(BaseModel):
    """对齐 `CounterpartyInfoRespVO`（实际是 ReqVO，命名沿用 Java）。"""

    model_config = ConfigDict(extra="allow")

    type: str = Field(..., min_length=1, description="业务类型 TRS / OPTION")
    roomId: str = Field(..., min_length=1, description="群ID")
    messageId: int | None = None
    orderId: str | None = None
    userId: str | None = None


# ============================================================
# 通用响应辅助
# ============================================================


def common_ok(data: Any = None) -> dict[str, Any]:
    """Java `CommonResult.success(data)` → `{code:0, data, msg:"success"}`。"""
    return {"code": 0, "data": data, "msg": "success"}


def common_fail(code: int = 400, msg: str = "业务错误") -> dict[str, Any]:
    return {"code": code, "data": None, "msg": msg}
