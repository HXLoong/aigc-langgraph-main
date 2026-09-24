"""swap 子图的 Pydantic Output 模型。

字段命名严格对齐 Java enum `SwapIntentionType`（7 值，ADR 0001 D2）。
LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.extraction.fields import CandidateDescription, CandidateInputName
from app.extraction.intent_evidence import IntentEvidenceOutput
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


class SwapIntentOutput(IntentEvidenceOutput):
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

    order_id: Annotated[str | None, CandidateDescription('只提取H-开头的互换订单号，或存在引用订单卡时的序号定位原文；裸证券数字代码、期货合约代码不是订单号；不生成单号')] = Field(default=None, alias="orderId", description="互换订单号 H-YYYYMMDD-XXXXXXXXXX；改单 / 补参时来自引用消息，全新下单 → null")
    place_order_ultra_contract_code: Annotated[str | None, CandidateDescription('用户明确给出的合约代码原文')] = Field(default=None, alias="placeOrderUltraContractCode", description="合约代码（用户明确给出时）")
    place_order_wind_code: Annotated[str | None, CandidateDescription('证券表达原文；名称加代码可取完整表达、单独名称或单独代码。value 不含其后的数量、@价格、交易对手、执行修饰语及独立的港股/A股等市场限定词；只给代码和数量也只取代码')] = Field(default=None, alias="placeOrderWindCode", description="标的原文（代码或名称片段，逐字保留；最终证券识别由后端负责）")
    place_order_transaction_type: Annotated[SwapTransactionType | None, CandidateInputName("market_selection"), CandidateDescription('仅本轮明确的市场或交易通道限定，如港股、美股、深港通；不是买卖方向、价格类型、算法、金额、数量单位或对手。未明确市场时为 null；证券代码里的交易所后缀不算用户选市场。港股不等于深港通或沪港通，不推断通道，不根据证券名称推断；保留原词，不转枚举')] = Field(default=None, alias="placeOrderTransactionType", description="交易品种：A_SHARE / HK_STOCK / US_STOCK / SZ_HK_CONNECT / SH_HK_CONNECT / CHN_FUTURE / CROSS_FUTURE")
    place_order_quantity: Annotated[int | None, CandidateDescription('委托数量原文，保留正负号及股、手、万等单位，负数不取绝对值，不展开数量；数量正负不能代替明确买卖方向')] = Field(default=None, alias="placeOrderQuantity", description="委托数量（股 / 手系单位展开后的整数）")
    place_order_quantity_hand: Annotated[int | None, CandidateDescription('旧兼容字段，本次抽取留空；手数原文使用 placeOrderQuantity')] = Field(default=None, alias="placeOrderQuantityHand", description="旧字段：按手表达的数量（新提示词不再要求填写）")  # 旧字段，见 docstring
    place_order_quantity_unit: Annotated[SwapQuantityUnit | None, CandidateDescription('用户或表头明确提供的数量单位原文，不转枚举')] = Field(default=None, alias="placeOrderQuantityUnit", description="数量单位：HAND 手系 / SHARE 股系 / AMOUNT 金额（落 placeOrderNotional）")
    place_order_order_direction: Annotated[SwapOrderDirection | None, CandidateDescription('仅从本轮连续原文提取明确买卖动作的核心原文片段，如暫買取買、已沽取沽、買入了取買入；不能把暂/已/了等修饰作为方向值。仅清仓、平仓、全减、减仓而未明确多空时方向为空，平仓动作另填平仓意图。evidence保留完整上下文及否定/条件；不能通过抠字抹掉否定、条件或历史陈述。不从持仓范围或数量正负推断方向，未明确为 null；不得从 quote/history 复制动作，不转枚举')] = Field(default=None, alias="placeOrderOrderDirection", description="方向：BUY 买入 / SELL 卖出 / SHORT_OPEN 卖空 / SHORT_CLOSE 平空")
    place_order_price_type: Annotated[SwapPriceType | None, CandidateDescription('仅限价或市价类型原文，含对应英文缩写；均价、跟量属于算法策略，不填本字段；集合竞价属于盘前执行要求，填盘前字段，不是价格类型。未明确价格类型为 null，不从算法推导，不转枚举')] = Field(default=None, alias="placeOrderPriceType", description="价格类型：LimitOrder 限价 / MarketOrder 市价")
    place_order_algorithm_type: Annotated[SwapAlgorithmType | None, CandidateDescription('只提取明确算法名称：POV/跟量、TWAP/全天均价、VWAP等；名称与数字比例分开提取。最大跟量、尽快、ASAP是快速执行意图，只填 hasFastExecutionIntent，本字段为 null。均价或均價后直接跟价格数字时表示价格信息，不作为算法。算法与执行风格同时出现时不遗漏明确算法名；value 不附带风格、比例或价格。没有明确算法则为 null；不补默认算法或比例')] = Field(default=None, alias="placeOrderAlgorithmType", description="算法：POV / TWAP / VWAP / ICEBERG / SNIPER")
    place_order_price: Annotated[float | int | None, CandidateDescription('本笔明确价格的数字原文，不包含限价/元/股等相邻修饰；evidence保留完整价格条件。卖出不低于某价格和买入不高于某价格可提取对应限价数字，反向或无法对应限价的条件不得丢弃后伪装为固定价格')] = Field(default=None, alias="placeOrderPrice", description="限价价格（数字）")
    place_order_pov_percent: Annotated[float | int | None, CandidateDescription('本笔跟量比例原文，保留百分号；比例与算法分别提取，算法名不能因紧邻比例而遗漏；value 取比例片段，evidence 可包含相邻算法名，不换算')] = Field(default=None, alias="placeOrderPovPercent", description="POV 跟量比例（数字，不带 %）")
    place_order_total_pov_percent: Annotated[float | int | None, CandidateDescription('总单跟量比例原文，保留百分号')] = Field(default=None, alias="placeOrderTotalPovPercent", description="总单 POV 比例（总单场景）")
    place_order_display_qty: Annotated[int | None, CandidateDescription('冰山单可见委托数量原文，保留单位')] = Field(default=None, alias="placeOrderDisplayQty", description="可见委托量（冰山单）")
    place_order_max_vol: Annotated[float | int | None, CandidateDescription('最大成交量限制原文，保留单位')] = Field(default=None, alias="placeOrderMaxVol", description="最大成交量限制")
    place_order_start_time: Annotated[str | None, CandidateDescription('算法开始钟点原文，仅显式 HH:MM 或中文冒号的时分；不补日期或时间字符。全天、开盘、到收盘等自然时段不填本字段，无钟点为 null，不推算市场时间')] = Field(default=None, alias="placeOrderStartTime", description="算法开始时间 HH:MM")
    place_order_end_time: Annotated[str | None, CandidateDescription('算法结束钟点原文，仅显式 HH:MM 或中文冒号的时分；不补日期或时间字符。全天、开盘、到收盘等自然时段不填本字段，无钟点为 null，不推算市场时间')] = Field(default=None, alias="placeOrderEndTime", description="算法结束时间 HH:MM")
    place_order_relative_time_minutes: Annotated[float | int | None, CandidateDescription('有明确长度的相对时长原文，保留数字及分钟、小时单位或半小时表达，不换算；全天、到收盘等未给出具体时长时为 null')] = Field(default=None, alias="placeOrderRelativeTimeMinutes", description="相对时间窗（分钟，如「30 分钟内」）")
    place_order_shortname: Annotated[str | None, CandidateDescription('交易对手名称原文，可结合 context.counterparties 和本轮角色词区分对手与标的；不包含相邻数量或证券名称，不替换为参考列表中的完整名称，不能把参考数据作为指名证据')] = Field(default=None, alias="placeOrderShortname", description="交易对手 shortName（完整匹配优先，唯一简写次之）")
    place_order_quantity_total: Annotated[int | None, CandidateDescription('总单数量原文，保留单位，不展开')] = Field(default=None, alias="placeOrderQuantityTotal", description="总量（总单场景）")
    place_order_premarket: Annotated[bool | None, CandidateDescription('盘前、集合竞价等盘前时段原文；开盘、尽快不算，没有则 null；不输出布尔值')] = Field(default=None, alias="placeOrderPremarket", description="是否盘前")
    place_order_notional: Annotated[float | int | None, CandidateDescription('仅委托主体为金额时提取，保留币种和单位。已有明确股数/手数且另有约/大概/左右金额时，该金额是参考估值，不当作第二个委托金额；仅给约数金额时保留限定词以供校验，不能删除约数词后当作精确金额。不换算')] = Field(default=None, alias="placeOrderNotional", description="名义本金 / 金额（数量单位为 AMOUNT 时）")
    place_order_notional_currency: Annotated[SwapNotionalCurrency | None, CandidateDescription('币种原文，不转枚举')] = Field(default=None, alias="placeOrderNotionalCurrency", description="名义本金币种：CNY / USD / HKD / EUR / GBP / JPY / AUD / NZD / CNH")
    place_order_entrust_ratio: Annotated[float | int | None, CandidateDescription('仅本笔明确比例或全量/半量原文，如全部、清仓、一半、50%。部分卖出/剩余而未给比例不是可计算比例，已有精确股数且没有全量或比例则为空。evidence须在同一连续原文中证明本笔动作与范围，不能跨订单或引用历史动作；持仓状态描述本身不充当指令，不填股数、不计算比例')] = Field(default=None, alias="placeOrderEntrustRatio", description="委托比例（可与 placeOrderQuantity 同时非 null）")
    place_order_close_intent: Annotated[bool | None, CandidateDescription('仅本轮明确平仓、清仓、减仓等动作原文，或同时包含卖出动作与持仓范围的连续原文；value 不接受仅含范围的片段，涉及持仓范围时，evidence 必须在同一连续原文内证明本笔动作与范围的关系，不从 quote/history 复制本轮动作；单纯持仓说明或未明确动作时为 null，不输出布尔值')] = Field(default=None, alias="placeOrderCloseIntent", description="是否平仓意图（减仓 / 平掉类表达）")
    has_fast_execution_intent: Annotated[bool | None, CandidateDescription('表达最大跟量、尽快或ASAP等快速执行的原文；不放入算法名称字段，不由此填默认算法或比例；原文若否定或带条件必须保留限定词，不输出布尔值')] = Field(default=None, alias="hasFastExecutionIntent", description="是否最大跟量 / 快速执行语义（按 system 规则判定）")


class SwapPlaceOrderParams(WireModel):
    """swap.place_order 节点 LLM 输出。

    与 Dify prompt 顶层结构一致：`{"type": "place_order_request", "orderList": [...]}`。
    `extra="ignore"` 接受 LLM 输出的 `type` 字段（被丢弃，不影响业务）。
    """

    model_config = ConfigDict(extra="ignore")

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

    model_config = ConfigDict(extra="ignore")

    order_id: str | None = Field(default=None, alias="orderId", description="目标订单号（引用消息中的 H- 单号）")
    order_seq: int | None = Field(default=None, alias="orderSeq", description="目标订单在 candidate_list 中的序号（orderId 缺失时用）")
    idx: int | None = Field(default=None, description="目标订单下标（0 起；orderId / orderSeq 都缺失时的兜底）")
    seq: int | None = Field(default=None, description="候选标的在本单 candidates 中的序号（seq → code）")
    direct_ref: str | None = Field(default=None, alias="directRef", description="用户原文中的候选代码或名称指针；必须唯一命中本订单候选，不得直接成为最终代码")
    evidence: str = Field(default="", description="本轮原文的连续选择片段，多订单必须含明确订单范围")
    confidence: float | None = Field(default=None, ge=0, le=1, description="选择识别置信度；模型指针必须提供，不能替代原文与范围校验")


class SwapSelectTickerOutput(BaseModel):
    """swap.select_ticker 节点 LLM 输出：未切换标的时 picks 为空数组。"""

    model_config = ConfigDict(extra="ignore")

    picks: list[SwapTickerPick] = Field(default_factory=list, description="切换标的的指针列表；未切换 → []（解析为空时保留原 windCode，非破坏）")


class SwapCounterpartyPick(WireModel):
    """互换-选择交易对手 单条指针（letter/ordinal/directName 三选一）。"""

    model_config = ConfigDict(extra="ignore")

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

    model_config = ConfigDict(extra="ignore")

    has_signal: bool = Field(default=False, alias="hasSignal", description="用户本次消息是否在选择 / 切换交易对手")
    picks: list[SwapCounterpartyPick] = Field(default_factory=list, description="选择对手的指针列表；无信号 → []（解析为空时保留原 shortName，非破坏）")


class SwapFreshCounterpartyMatch(WireModel):
    """Dify 1786439000001：完整候选名称及原文证据，均必填。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    short_name: str = Field(alias="shortName", description="候选列表中的完整 shortName（逐字，不得改写）")
    evidence: str = Field(description="用户原话中支持该名称的片段（必须是原文子串）")


class SwapFreshCounterpartyOutput(WireModel):
    """全新下单召回结果，必填约束及额外字段限制对齐 Dify schema。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    has_signal: bool = Field(alias="hasSignal", description="用户原话中是否包含交易对手指名（同一候选内多名字→不唯一时不采纳）")
    matches: list[SwapFreshCounterpartyMatch] = Field(description="从原话召回的交易对手匹配列表；无召回 → []")


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
    "SwapTickerPick",
    "SwapSelectTickerOutput",
    "SwapCounterpartyPick",
    "SwapSelectCounterpartyOutput",
    "SwapFreshCounterpartyMatch",
    "SwapFreshCounterpartyOutput",
]
