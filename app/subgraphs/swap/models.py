"""swap 子图的 Pydantic Output 模型。

字段命名严格对齐 Java enum `SwapIntentionType`（7 值，ADR 0001 D2）。
LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。
"""
# ruff: noqa: N815
# 说明：本文件字段名逐字对齐 Dify structured_output / Java DTO 的 camelCase 原文
# （orderId / placeOrderWindCode / hasSignal 等），改成 snake_case 会破坏与 Dify
# prompt JSON schema、Java 后端字段名的 1:1 映射（详见 CLAUDE.md「提示词不硬编码」
# 纪律 + docs/api-contracts/java-backend.md）。全文件统一豁免这条命名检查，比在
# 40 多处字段逐行加豁免注释更清晰。
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

    model_config = ConfigDict(extra="ignore")

    type: SwapIntentType


# ============================================================
# 下单/改单参数（swap.place_order）
# ============================================================


#: 交易类型（对齐 Java GoatsTransactionType 枚举，见 docs/api-contracts/java-backend.md:210）
#: Dify prompt 中"深港通"→SZ_HK_CONNECT，"沪港通"→SH_HK_CONNECT，"境内期货"→CHN_FUTURE，"跨境期货"→CROSS_FUTURE
#: FUTURES/FUND/INDEX/BOND/OTHERS 是历史兼容值，新值是 Java 后端真正接受的字面量
SwapTransactionType = Literal[
    "A_SHARE",
    "HK_STOCK",
    "US_STOCK",
    "SZ_HK_CONNECT",
    "SH_HK_CONNECT",
    "CHN_FUTURE",
    "CROSS_FUTURE",
    "FUTURES",
    "FUND",
    "INDEX",
    "BOND",
    "OTHERS",
]

#: 买卖方向（对齐 Java GoatsOrderDirection，4 个值；swap-023 等"SHORT_OPEN"被 LLM 抽
#: 出后撞 Pydantic ValidationError 的回归保护）
#: BUY 买入 / SELL 卖出 / SHORT_OPEN 卖空 / SHORT_CLOSE 平空
SwapOrderDirection = Literal["BUY", "SELL", "SHORT_OPEN", "SHORT_CLOSE"]

#: 价格类型
SwapPriceType = Literal["LimitOrder", "MarketOrder"]

#: 算法类型
#: 算法类型（与 Java GoatsAlgoType 一致：POV/TWAP/VWAP/ICEBERG/SNIPER；M2 阶段 LLM 主要用 POV/TWAP/VWAP）。
SwapAlgorithmType = Literal["POV", "TWAP", "VWAP", "ICEBERG", "SNIPER"]

#: 委托数量单位（DSL v2 新增，互换-节点-下单.md「placeOrderQuantityUnit」）。
#: HAND=手系单位落 quantity；SHARE=股系单位落 quantity；AMOUNT=金额落 notional。
SwapQuantityUnit = Literal["HAND", "SHARE", "AMOUNT"]

#: 委托名义本金币种（DSL v2 新增，互换-节点-下单.md「placeOrderNotionalCurrency」）。
SwapNotionalCurrency = Literal[
    "CNY", "USD", "HKD", "EUR", "GBP", "JPY", "AUD", "NZD", "CNH"
]


class SwapOrderItem(BaseModel):
    """swap orderList 中的单个订单条目（与 DSL v2 互换-节点-下单.md 字段对齐）。

    全部字段 Optional —— prompt 允许 null 表示"用户未提供"。
    `extra="ignore"` 让 LLM 输出的顶层 type 字段或其他多余字段被丢弃，
    不触发 ValidationError。

    DSL v2 新增 7 字段（互换-节点-下单.md structured_output，2026-08 版）：
    hasFastExecutionIntent / placeOrderCloseIntent / placeOrderEntrustRatio /
    placeOrderNotional / placeOrderNotionalCurrency / placeOrderQuantityUnit /
    placeOrderRelativeTimeMinutes。

    `placeOrderQuantityHand` 是旧 DSL 字段，新提示词已不再要求 LLM 填写（改用
    placeOrderQuantityUnit="HAND" + placeOrderQuantity 表达），但保留在模型里
    ——`app/nodes/render.py`（主图渲染节点，swap 域外）仍读取该字段区分"手/股"
    单位显示，删除会导致其静默失效；后续应由 render 域的 PR 迁移到读
    placeOrderQuantityUnit。
    """

    model_config = ConfigDict(extra="ignore")

    orderId: str | None = None
    placeOrderUltraContractCode: str | None = None
    placeOrderWindCode: str | None = None
    placeOrderTransactionType: SwapTransactionType | None = None
    placeOrderQuantity: int | None = None
    placeOrderQuantityHand: int | None = None  # 旧字段，见 docstring
    placeOrderQuantityUnit: SwapQuantityUnit | None = None
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
    placeOrderRelativeTimeMinutes: float | int | None = None
    placeOrderShortname: str | None = None
    placeOrderQuantityTotal: int | None = None
    placeOrderPremarket: bool | None = None
    placeOrderNotional: float | int | None = None
    placeOrderNotionalCurrency: SwapNotionalCurrency | None = None
    placeOrderEntrustRatio: float | int | None = None
    placeOrderCloseIntent: bool | None = None
    hasFastExecutionIntent: bool | None = None


class SwapPlaceOrderParams(BaseModel):
    """swap.place_order 节点 LLM 输出。

    与 Dify prompt 顶层结构一致：`{"type": "place_order_request", "orderList": [...]}`。
    `extra="ignore"` 接受 LLM 输出的 `type` 字段（被丢弃，不影响业务）。
    """

    model_config = ConfigDict(extra="ignore")

    orderList: list[SwapOrderItem] = Field(default_factory=list)


# ============================================================
# 确认/撤单/查询 共享 schema（confirm / cancel / query）
#
# 三个节点输出共用 schema：仅含 orderList[orderId]。
# orderId 允许 null（与 Dify 原 schema 一致，表示"找不到订单号"兜底）。
# ============================================================


class SwapOrderRefItem(BaseModel):
    """轻量订单引用（与 Dify swap/confirm/cancel/query 输出 schema 对齐）。"""

    model_config = ConfigDict(extra="ignore")

    orderId: str | None = None


class SwapConfirmParams(BaseModel):
    """swap.confirm 合并版输出（confirm_order + confirm_cancel_order +
    confirm_modify_order 三子意图共用，靠 expected_action 区分）。
    """

    model_config = ConfigDict(extra="ignore")

    orderList: list[SwapOrderRefItem] = Field(default_factory=list)


class SwapCancelParams(BaseModel):
    """swap.cancel 输出（cancel_order_request 意图）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[SwapOrderRefItem] = Field(default_factory=list)


class SwapQueryParams(BaseModel):
    """swap.query_order 输出（query_order_status 意图）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[SwapOrderRefItem] = Field(default_factory=list)


# ============================================================
# 标的/交易对手选择指针（swap.select_ticker / swap.select_counterparty）
#
# DSL v2 新节点：只判断用户是否在切换候选标的 / 选择交易对手，输出指针
# （不输出最终 windCode / shortName，由 app/subgraphs/swap/aggregate.py
# 的确定性查表覆盖到 swap.place_order 的 orderList 上）。
# ============================================================


class SwapTickerPick(BaseModel):
    """互换-选择标的 单条指针（对齐 candidate_list 定位 + candidates.seq）。"""

    model_config = ConfigDict(extra="ignore")

    orderId: str | None = None
    orderSeq: int | None = None
    idx: int | None = None
    seq: int | None = None
    directRef: str | None = None


class SwapSelectTickerOutput(BaseModel):
    """swap.select_ticker 节点 LLM 输出：未切换标的时 picks 为空数组。"""

    model_config = ConfigDict(extra="ignore")

    picks: list[SwapTickerPick] = Field(default_factory=list)


class SwapCounterpartyPick(BaseModel):
    """互换-选择交易对手 单条指针（letter/ordinal/directName 三选一）。"""

    model_config = ConfigDict(extra="ignore")

    orderId: str | None = None
    orderSeq: int | None = None
    idx: int | None = None
    letter: str | None = None
    ordinal: int | None = None
    directName: str | None = None


class SwapSelectCounterpartyOutput(BaseModel):
    """swap.select_counterparty 节点 LLM 输出：hasSignal=False 时无对手选择信号。"""

    model_config = ConfigDict(extra="ignore")

    hasSignal: bool = False
    picks: list[SwapCounterpartyPick] = Field(default_factory=list)


__all__ = [
    "SwapIntentType",
    "SwapIntentOutput",
    "SwapTransactionType",
    "SwapOrderDirection",
    "SwapPriceType",
    "SwapAlgorithmType",
    "SwapQuantityUnit",
    "SwapNotionalCurrency",
    "SwapOrderItem",
    "SwapPlaceOrderParams",
    "SwapOrderRefItem",
    "SwapConfirmParams",
    "SwapCancelParams",
    "SwapQueryParams",
    "SwapTickerPick",
    "SwapSelectTickerOutput",
    "SwapCounterpartyPick",
    "SwapSelectCounterpartyOutput",
]
