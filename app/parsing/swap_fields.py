"""互换接口字段与候选选择指针，业务值由 Java 校验。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.parsing.scalars import CandidateScalar
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
#: 算法类型（与 Java GoatsAlgoType 一致：POV/TWAP/VWAP/ICEBERG/SNIPER；LLM 主要用 POV/TWAP/VWAP）。
SwapAlgorithmType = Literal["POV", "TWAP", "VWAP", "ICEBERG", "SNIPER"]

#: 委托数量单位（DSL v2 新增，互换-节点-下单.md「placeOrderQuantityUnit」）。
#: HAND=手系单位落 quantity；SHARE=股系单位落 quantity；AMOUNT=金额落 notional。
SwapQuantityUnit = Literal["HAND", "SHARE", "AMOUNT"]

#: 委托名义本金币种（DSL v2 新增，互换-节点-下单.md「placeOrderNotionalCurrency」）。
SwapNotionalCurrency = Literal[
    "CNY", "USD", "HKD", "EUR", "GBP", "JPY", "AUD", "NZD", "CNH"
]


class SwapOrderItem(WireModel):
    """本次互换接口参数。保留独立订单，业务数值与默认值由 Java 校验。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = Field(default=None, alias="orderId", description="互换订单号 H-YYYYMMDD-XXXXXXXXXX；改单 / 补参时来自引用消息，全新下单 → null")
    place_order_ultra_contract_code: CandidateScalar | None = Field(default=None, alias="placeOrderUltraContractCode", description="合约代码（用户明确给出时）")
    place_order_wind_code: CandidateScalar | None = Field(default=None, alias="placeOrderWindCode", description="标的原文（代码或名称片段，逐字保留；最终证券识别由后端负责）")
    place_order_transaction_type: CandidateScalar | None = Field(
        default=None, alias="placeOrderTransactionType",
        description="这是用户明确指定的市场/通道，不是对标的所属市场的分类预测，默认null。"
        "仅本次原文明示市场词才填写：A股→A_SHARE，港股→HK_STOCK，"
        "美股→US_STOCK，深港通→SZ_HK_CONNECT，沪港通→SH_HK_CONNECT，"
        "境内期货→CHN_FUTURE，跨境期货→CROSS_FUTURE。未明示为null，由Java识别。"
        "严禁从证券名称、代码、交易所后缀、合约形式或手数推断；仅出现期货或手不等于境内期货。"
        "有值时字段证据必须是本次明确的市场/通道词，不能用证券或数量代替。",
    )
    place_order_quantity: CandidateScalar | None = Field(
        default=None, alias="placeOrderQuantity",
        description="股/手委托的完整整数数量，明确倍率须展开；AMOUNT金额委托必须为null。"
        "只有万/w/百万等倍率、没有股数或手数单位时走金额字段，不能放进quantity。"
        "港股/美股/A股是市场词，其中的股不是委托数量单位，即使市场词紧邻数值也一样。"
        "明确数量@价格格式的@前数值仍按数量提取，不换算手与股。",
    )
    place_order_quantity_hand: CandidateScalar | None = Field(default=None, alias="placeOrderQuantityHand", description="旧字段：按手表达的数量（新提示词不再要求填写）")  # 旧字段，见 docstring
    place_order_quantity_unit: CandidateScalar | None = Field(
        default=None, alias="placeOrderQuantityUnit",
        description="只按委托数值紧邻的单位判断：手/lot/张→HAND，股→SHARE；"
        "先排除市场词：港股/美股/A股中的股不是数量单位，金额后紧跟市场词仍按金额判断。"
        "金额词、币种或无股手的万/w/千/k/亿量词→AMOUNT，数值落placeOrderNotional。"
        "纯数字无单位可为null；不能根据标的或市场补单位。HAND/SHARE使用placeOrderQuantity，"
        "AMOUNT使用完整金额，两种数值字段不同时填写；手数不换算成股数。"
        "本次明确金额已填placeOrderNotional时，必须同时填AMOUNT；明确股数/手数也必须给对应单位，"
        "不能因市场或币种未提供而省略已明确的单位。"
        "数量@价格表达中，@前为委托数量，不能因含倍率而改成金额。",
    )
    place_order_order_direction: CandidateScalar | None = Field(
        default=None, alias="placeOrderOrderDirection",
        description="本次明确的买卖方向必须提取，不依赖市场、币种或数量是否齐全。"
        "完整开平仓词优先：买入开仓→BUY，买入平仓→SHORT_CLOSE，卖出开仓→SHORT_OPEN，"
        "卖出平仓→SELL；其余买/买入/買入→BUY，卖/卖出/賣出/沽出→SELL，卖空→SHORT_OPEN，"
        "平空→SHORT_CLOSE。单字买/卖也属于明确动作，不能漏提；未提供方向不默认买入。",
    )
    place_order_price_type: CandidateScalar | None = Field(default=None, alias="placeOrderPriceType", description="价格类型：LimitOrder 限价 / MarketOrder 市价")
    place_order_algorithm_type: CandidateScalar | None = Field(default=None, alias="placeOrderAlgorithmType", description="算法：POV / TWAP / VWAP / ICEBERG / SNIPER")
    place_order_price: CandidateScalar | None = Field(default=None, alias="placeOrderPrice", description="限价价格（数字）")
    place_order_pov_percent: CandidateScalar | None = Field(default=None, alias="placeOrderPovPercent", description="POV 跟量比例（数字，不带 %）")
    place_order_total_pov_percent: CandidateScalar | None = Field(default=None, alias="placeOrderTotalPovPercent", description="总单 POV 比例（总单场景）")
    place_order_display_qty: CandidateScalar | None = Field(default=None, alias="placeOrderDisplayQty", description="可见委托量（冰山单）")
    place_order_max_vol: CandidateScalar | None = Field(default=None, alias="placeOrderMaxVol", description="最大成交量限制")
    place_order_start_time: CandidateScalar | None = Field(default=None, alias="placeOrderStartTime", description="算法开始时间 HH:MM")
    place_order_end_time: CandidateScalar | None = Field(default=None, alias="placeOrderEndTime", description="算法结束时间 HH:MM")
    place_order_relative_time_minutes: CandidateScalar | None = Field(default=None, alias="placeOrderRelativeTimeMinutes", description="相对时间窗（分钟，如「30 分钟内」）")
    place_order_shortname: CandidateScalar | None = Field(default=None, alias="placeOrderShortname", description="交易对手 shortName（完整匹配优先，唯一简写次之）")
    place_order_quantity_total: CandidateScalar | None = Field(default=None, alias="placeOrderQuantityTotal", description="总量（总单场景）")
    place_order_premarket: CandidateScalar | None = Field(default=None, alias="placeOrderPremarket", description="是否盘前")
    place_order_notional: CandidateScalar | None = Field(
        default=None, alias="placeOrderNotional",
        description="仅AMOUNT委托填写展开后的完整金额数值（支持小数），"
        "本次提取须展开原文倍率：千/k/K=1000，万/w/W=10000，百万=1000000，亿=100000000。"
        "中文数词同样表达完整金额；不能只保留倍率前的数字，不能输出带单位或币种的字符串。"
        "fields.text仍逐字保留原金额及单位。已识别明确AMOUNT金额时不得漏填；"
        "非AMOUNT或未提供金额为null，不从股数、手数或价格计算金额。",
    )
    place_order_notional_currency: CandidateScalar | None = Field(
        default=None, alias="placeOrderNotionalCurrency",
        description="币种是独立的原文提取字段，不是根据已识别金额或市场计算的字段。"
        "仅AMOUNT且本次金额短语出现币种标记才填写；仅有数词和倍率必须为null，"
        "中文数词也不是人民币标记，不能给一笔未标币种的金额补CNY。先匹配复合币种词："
        "美元/美金/USD/$→USD，港元/港币/HKD→HKD，欧元/EUR/€→EUR，英镑/GBP→GBP，"
        "日元/JPY→JPY，澳元/AUD→AUD，新西兰元/NZD→NZD，离岸人民币/CNH→CNH；"
        "其余金额短语含元/人民币/CNY/￥时必须提取CNY，包括万元/千元/亿元的元。"
        "严格区分：12万或12w→null，12万元→CNY，12万港元→HKD。"
        "市场词位于金额前后或紧贴金额仍不是币种：港股买12万、买12万港股的币种都为null；"
        "只有金额中的港币/港元/HKD才支持HKD，港股一词只能支持交易品种，不能同时支持币种。"
        "港股/美股/A股、证券名称和代码后缀不是币种标记，"
        "禁止据此填写HKD/USD/CNY；价格中的元不能充当委托金额币种证据。"
        "有值时fields.text必须取本次金额中的币种标记；非AMOUNT为null。",
    )
    place_order_entrust_ratio: CandidateScalar | None = Field(default=None, alias="placeOrderEntrustRatio", description="委托比例（可与 placeOrderQuantity 同时非 null）")
    place_order_close_intent: CandidateScalar | None = Field(default=None, alias="placeOrderCloseIntent", description="是否平仓意图（减仓 / 平掉类表达）")
    has_fast_execution_intent: CandidateScalar | None = Field(default=None, alias="hasFastExecutionIntent", description="是否最大跟量 / 快速执行语义（按 system 规则判定）")


class SwapPlaceOrderParams(WireModel):
    """互换准备结果的订单列表；模型提取值直接用于接口装配。"""

    model_config = ConfigDict(extra="forbid")

    order_list: list[SwapOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；每条对应用户一笔委托，未给出的字段为 null")


# ============================================================
# 标的/交易对手选择指针（swap.select_ticker / swap.select_counterparty）
#
# DSL v2 新节点：只判断用户是否在切换候选标的 / 选择交易对手，输出指针
# （不输出最终 windCode / shortName，由 app/subgraphs/swap/aggregate.py
# 的确定性查表覆盖到 swap.place_order 的 orderList 上）。
# ============================================================


class SwapTickerPick(WireModel):
    """互换-选择标的 单条指针（对齐 candidate_list 定位 + candidates.seq）。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = Field(default=None, alias="orderId", description="目标订单号（引用消息中的 H- 单号）")
    order_seq: int | None = Field(default=None, alias="orderSeq", description="目标订单在 candidate_list 中的序号（orderId 缺失时用）")
    idx: int | None = Field(default=None, description="目标订单下标（0 起；orderId / orderSeq 都缺失时的兜底）")
    seq: int | None = Field(default=None, description="候选标的在本单 candidates 中的序号（seq → code）")
    direct_ref: str | None = Field(default=None, alias="directRef", description="用户原文中的候选代码或名称指针；必须唯一命中本订单候选，不得直接成为最终代码")
    evidence: str = Field(default="", description="本轮原文的连续选择片段，多订单必须含明确订单范围")
    confidence: float | None = Field(default=None, ge=0, le=1, description="选择识别置信度；模型指针必须提供，不能替代原文与范围校验")


class SwapSelectTickerOutput(BaseModel):
    """swap.select_ticker 节点 LLM 输出：未切换标的时 picks 为空数组。"""

    model_config = ConfigDict(extra="forbid")

    picks: list[SwapTickerPick] = Field(default_factory=list, description="切换标的的指针列表；未切换 → []（解析为空时保留原 windCode，非破坏）")


class SwapCounterpartyPick(WireModel):
    """互换-选择交易对手 单条指针（letter/ordinal/directName 三选一）。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = Field(default=None, alias="orderId", description="目标订单号（引用消息中的 H- 单号）")
    order_seq: int | None = Field(default=None, alias="orderSeq", description="目标订单序号（单订单场景可省略）")
    idx: int | None = Field(default=None, description="目标订单下标（0 起；orderId / orderSeq 都缺失时的兜底）")
    letter: str | None = Field(default=None, description="对手列表中的字母标识（如 A / B，对应 sort）")
    ordinal: int | None = Field(default=None, description="对手列表中的第 N 个（1 起，映射为 sort 字母）")
    direct_name: str | None = Field(default=None, alias="directName", description="对手名称原文（精确匹配优先，唯一子串次之；多命中不算）")
    evidence: str = Field(default="", description="本轮原文的连续选择片段，多订单必须含明确订单范围")
    confidence: float | None = Field(default=None, ge=0, le=1, description="选择识别置信度；模型指针必须提供，不能替代原文与范围校验")


class SwapSelectCounterpartyOutput(WireModel):
    """swap.select_counterparty 节点 LLM 输出：hasSignal=False 时无对手选择信号。"""

    model_config = ConfigDict(extra="forbid")

    has_signal: bool = Field(default=False, alias="hasSignal", description="用户本次消息是否在选择 / 切换交易对手")
    picks: list[SwapCounterpartyPick] = Field(default_factory=list, description="选择对手的指针列表；无信号 → []（解析为空时保留原 shortName，非破坏）")






__all__ = [
    "SwapIntentType",
    "SwapTransactionType",
    "SwapOrderDirection",
    "SwapPriceType",
    "SwapAlgorithmType",
    "SwapQuantityUnit",
    "SwapNotionalCurrency",
    "SwapOrderItem",
    "SwapPlaceOrderParams",
    "SwapTickerPick",
    "SwapSelectTickerOutput",
    "SwapCounterpartyPick",
    "SwapSelectCounterpartyOutput",
]
