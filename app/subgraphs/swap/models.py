"""swap 子图的 Pydantic Output 模型。

字段命名严格对齐 Java enum `SwapIntentionType`（7 值，ADR 0001 D2）。
LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.wire_model import WireModel

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

    type: SwapIntentType = Field(description="互换意图，取 7 个枚举值之一")


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


class SwapOrderItem(WireModel):
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

    order_id: str | None = Field(default=None, alias="orderId", description="互换订单号 H-YYYYMMDD-XXXXXXXXXX；改单 / 补参时来自引用消息，全新下单 → null")
    place_order_ultra_contract_code: str | None = Field(default=None, alias="placeOrderUltraContractCode", description="合约代码（用户明确给出时）")
    place_order_wind_code: str | None = Field(default=None, alias="placeOrderWindCode", description="标的原文（代码或名称片段，逐字保留；标准化由 ticker resolver 负责）")
    place_order_transaction_type: SwapTransactionType | None = Field(default=None, alias="placeOrderTransactionType", description="交易品种：A_SHARE / HK_STOCK / US_STOCK / SZ_HK_CONNECT / SH_HK_CONNECT / CHN_FUTURE / CROSS_FUTURE")
    place_order_quantity: int | None = Field(default=None, alias="placeOrderQuantity", description="委托数量（股 / 手系单位展开后的整数）")
    place_order_quantity_hand: int | None = Field(default=None, alias="placeOrderQuantityHand", description="旧字段：按手表达的数量（新提示词不再要求填写）")  # 旧字段，见 docstring
    place_order_quantity_unit: SwapQuantityUnit | None = Field(default=None, alias="placeOrderQuantityUnit", description="数量单位：HAND 手系 / SHARE 股系 / AMOUNT 金额（落 placeOrderNotional）")
    place_order_order_direction: SwapOrderDirection | None = Field(default=None, alias="placeOrderOrderDirection", description="方向：BUY 买入 / SELL 卖出 / SHORT_OPEN 卖空 / SHORT_CLOSE 平空")
    place_order_price_type: SwapPriceType | None = Field(default=None, alias="placeOrderPriceType", description="价格类型：LimitOrder 限价 / MarketOrder 市价")
    place_order_algorithm_type: SwapAlgorithmType | None = Field(default=None, alias="placeOrderAlgorithmType", description="算法：POV / TWAP / VWAP / ICEBERG / SNIPER")
    place_order_price: float | int | None = Field(default=None, alias="placeOrderPrice", description="限价价格（数字）")
    place_order_pov_percent: float | int | None = Field(default=None, alias="placeOrderPovPercent", description="POV 跟量比例（数字，不带 %）")
    place_order_total_pov_percent: float | int | None = Field(default=None, alias="placeOrderTotalPovPercent", description="总单 POV 比例（总单场景）")
    place_order_display_qty: int | None = Field(default=None, alias="placeOrderDisplayQty", description="可见委托量（冰山单）")
    place_order_max_vol: float | int | None = Field(default=None, alias="placeOrderMaxVol", description="最大成交量限制")
    place_order_start_time: str | None = Field(default=None, alias="placeOrderStartTime", description="算法开始时间 HH:MM")
    place_order_end_time: str | None = Field(default=None, alias="placeOrderEndTime", description="算法结束时间 HH:MM")
    place_order_relative_time_minutes: float | int | None = Field(default=None, alias="placeOrderRelativeTimeMinutes", description="相对时间窗（分钟，如「30 分钟内」）")
    place_order_shortname: str | None = Field(default=None, alias="placeOrderShortname", description="交易对手 shortName（完整匹配优先，唯一简写次之）")
    place_order_quantity_total: int | None = Field(default=None, alias="placeOrderQuantityTotal", description="总量（总单场景）")
    place_order_premarket: bool | None = Field(default=None, alias="placeOrderPremarket", description="是否盘前")
    place_order_notional: float | int | None = Field(default=None, alias="placeOrderNotional", description="名义本金 / 金额（数量单位为 AMOUNT 时）")
    place_order_notional_currency: SwapNotionalCurrency | None = Field(default=None, alias="placeOrderNotionalCurrency", description="名义本金币种：CNY / USD / HKD / EUR / GBP / JPY / AUD / NZD / CNH")
    place_order_entrust_ratio: float | int | None = Field(default=None, alias="placeOrderEntrustRatio", description="委托比例（可与 placeOrderQuantity 同时非 null）")
    place_order_close_intent: bool | None = Field(default=None, alias="placeOrderCloseIntent", description="是否平仓意图（减仓 / 平掉类表达）")
    has_fast_execution_intent: bool | None = Field(default=None, alias="hasFastExecutionIntent", description="是否最大跟量 / 快速执行语义（按 system 规则判定）")


class SwapPlaceOrderParams(WireModel):
    """swap.place_order 节点 LLM 输出。

    与 Dify prompt 顶层结构一致：`{"type": "place_order_request", "orderList": [...]}`。
    `extra="ignore"` 接受 LLM 输出的 `type` 字段（被丢弃，不影响业务）。
    """

    model_config = ConfigDict(extra="ignore")

    order_list: list[SwapOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；每条对应用户一笔委托，未给出的字段为 null")


# ============================================================
# 确认/撤单/查询 共享 schema（confirm / cancel / query）
#
# 三个节点输出共用 schema：仅含 orderList[orderId]。
# orderId 允许 null（与 Dify 原 schema 一致，表示"找不到订单号"兜底）。
# ============================================================


class SwapOrderRefItem(WireModel):
    """轻量订单引用（与 Dify swap/confirm/cancel/query 输出 schema 对齐）。"""

    model_config = ConfigDict(extra="ignore")

    order_id: str | None = Field(default=None, alias="orderId")


class SwapConfirmParams(WireModel):
    """swap.confirm 合并版输出（confirm_order + confirm_cancel_order +
    confirm_modify_order 三子意图共用，靠 expected_action 区分）。
    """

    model_config = ConfigDict(extra="ignore")

    order_list: list[SwapOrderRefItem] = Field(alias="orderList", default_factory=list)


class SwapCancelParams(WireModel):
    """swap.cancel 输出（cancel_order_request 意图）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[SwapOrderRefItem] = Field(alias="orderList", default_factory=list)


class SwapQueryParams(WireModel):
    """swap.query_order 输出（query_order_status 意图）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[SwapOrderRefItem] = Field(alias="orderList", default_factory=list)


# ============================================================
# 标的/交易对手选择指针（swap.select_ticker / swap.select_counterparty）
#
# DSL v2 新节点：只判断用户是否在切换候选标的 / 选择交易对手，输出指针
# （不输出最终 windCode / shortName，由 app/subgraphs/swap/aggregate.py
# 的确定性查表覆盖到 swap.place_order 的 orderList 上）。
# ============================================================


class SwapTickerPick(WireModel):
    """互换-选择标的 单条指针（对齐 candidate_list 定位 + candidates.seq）。"""

    model_config = ConfigDict(extra="ignore")

    order_id: str | None = Field(default=None, alias="orderId")
    order_seq: int | None = Field(default=None, alias="orderSeq")
    idx: int | None = None
    seq: int | None = None
    direct_ref: str | None = Field(default=None, alias="directRef")


class SwapSelectTickerOutput(BaseModel):
    """swap.select_ticker 节点 LLM 输出：未切换标的时 picks 为空数组。"""

    model_config = ConfigDict(extra="ignore")

    picks: list[SwapTickerPick] = Field(default_factory=list)


class SwapCounterpartyPick(WireModel):
    """互换-选择交易对手 单条指针（letter/ordinal/directName 三选一）。"""

    model_config = ConfigDict(extra="ignore")

    order_id: str | None = Field(default=None, alias="orderId")
    order_seq: int | None = Field(default=None, alias="orderSeq")
    idx: int | None = None
    letter: str | None = None
    ordinal: int | None = None
    direct_name: str | None = Field(default=None, alias="directName")


class SwapSelectCounterpartyOutput(WireModel):
    """swap.select_counterparty 节点 LLM 输出：hasSignal=False 时无对手选择信号。"""

    model_config = ConfigDict(extra="ignore")

    has_signal: bool = Field(default=False, alias="hasSignal")
    picks: list[SwapCounterpartyPick] = Field(default_factory=list)


class SwapFreshCounterpartyMatch(WireModel):
    """Dify 1786439000001：完整候选名称及原文证据，均必填。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    short_name: str = Field(alias="shortName")
    evidence: str


class SwapFreshCounterpartyOutput(WireModel):
    """全新下单召回结果，必填约束及额外字段限制对齐 Dify schema。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    has_signal: bool = Field(alias="hasSignal")
    matches: list[SwapFreshCounterpartyMatch]


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
    "SwapFreshCounterpartyMatch",
    "SwapFreshCounterpartyOutput",
]
