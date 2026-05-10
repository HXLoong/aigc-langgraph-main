"""swap 子图的 Pydantic Output 模型。

字段命名严格对齐 Java enum `SwapIntentionType`（7 值，ADR 0001 D2）。
LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# 意图分类（swap.intent）
# ============================================================


#: Java SwapIntentionType 7 值（CONTEXT.md / ADR 0001 D2）
SwapIntentType = Literal[
    "place_order_request",  # 下单/改单（Java 端共用，靠 orderId 区分）
    "cancel_order_request",
    "confirm_order",
    "confirm_cancel_order",
    "confirm_modify_order",
    "query_order_status",
    "unknown_intent",
]


class SwapIntentOutput(BaseModel):
    """swap.intent 节点的 LLM 输出 schema。"""

    model_config = ConfigDict(extra="forbid")

    type: SwapIntentType


# ============================================================
# 下单/改单参数（swap.place_order）
# ============================================================


#: 交易类型（对齐 Java placeOrderTransactionType 枚举）
SwapTransactionType = Literal[
    "A_SHARE",
    "HK_STOCK",
    "US_STOCK",
    "FUTURES",
    "FUND",
    "INDEX",
    "BOND",
    "OTHERS",
]

#: 买卖方向
SwapOrderDirection = Literal["BUY", "SELL"]

#: 价格类型
SwapPriceType = Literal["LimitOrder", "MarketOrder"]

#: 算法类型
SwapAlgorithmType = Literal["POV", "TWAP"]


class SwapOrderItem(BaseModel):
    """swap orderList 中的单个订单条目（与 Dify place_order.md 字段对齐）。

    19 个字段全部 Optional —— Dify prompt 允许 null 表示"用户未提供"。
    `extra="ignore"` 让 LLM 输出的顶层 type 字段或其他多余字段被丢弃，
    不触发 ValidationError。
    """

    model_config = ConfigDict(extra="ignore")

    orderId: str | None = None
    placeOrderUltraContractCode: str | None = None
    placeOrderWindCode: str | None = None
    placeOrderTransactionType: SwapTransactionType | None = None
    placeOrderQuantity: int | None = None
    placeOrderQuantityHand: int | None = None
    placeOrderOrderDirection: SwapOrderDirection | None = None
    placeOrderPriceType: SwapPriceType | None = None
    placeOrderAlgorithmType: SwapAlgorithmType | None = None
    placeOrderPrice: float | int | None = None
    placeOrderPovPercent: float | int | None = None
    placeOrderTotalPovPercent: float | int | None = None
    placeOrderDisplayQty: int | None = None
    placeOrderMaxVol: float | int | None = None
    placeOrderStartTime: str | None = None
    placeOrderEndTime: str | None = None
    placeOrderShortname: str | None = None
    placeOrderQuantityTotal: int | None = None
    placeOrderPremarket: bool | None = None


class SwapPlaceOrderParams(BaseModel):
    """swap.place_order 节点 LLM 输出。

    与 Dify prompt 顶层结构一致：`{"type": "place_order_request", "orderList": [...]}`。
    `extra="ignore"` 接受 LLM 输出的 `type` 字段（被丢弃，不影响业务）。
    """

    model_config = ConfigDict(extra="ignore")

    orderList: list[SwapOrderItem] = Field(default_factory=list)


__all__ = [
    "SwapIntentType",
    "SwapIntentOutput",
    "SwapTransactionType",
    "SwapOrderDirection",
    "SwapPriceType",
    "SwapAlgorithmType",
    "SwapOrderItem",
    "SwapPlaceOrderParams",
]
