"""期权接口字段：本次解析值与原文证据由联合契约分别保存。"""
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from app.parsing.scalars import CandidateScalar
from app.wire_model import WireModel

#: option 子图处理的 8 个意图（7 个基础意图 + unknown_intent；不含 close_order_*）
OptionIntentType = Literal[
    "new_inquiry",
    "place_order_from_quote",
    "confirm_order",
    "cancel_order_request",
    "request_cancel_order",
    "confirm_cancel_order",
    "query_order_status",
    "unknown_intent",
]




# ============================================================
# orderList item 共用 schema（extract 节点共用，Dify DSL v2；1 个 LLM + 2 个确定性）
# ============================================================


#: 期权下单方式枚举
OptionOrderType = Literal["市价单", "限价单", "POV", "TWAP"]

#: 期权类型枚举（Dify DSL v2 收窄为 3 值，不再支持"欧式看跌"/"气囊"）
OptionContractType = Literal["欧式看涨", "参与型看涨", "雪球"]


class OptionOrderItem(WireModel):
    """本次期权接口参数。未提供值为空，来源在联合结果 fields 中单独记录。"""

    model_config = ConfigDict(extra="forbid")

    order_id: str | None = Field(default=None, alias="orderId", description="订单号（Q-YYYYMMDD-XXXXXXXXXX），仅在用户或引用消息明确给出时填写，否则 null")
    #: 标的原文（用户原话片段，最终证券识别由后端负责）
    stock_code: CandidateScalar | None = Field(default=None, alias="stockCode", description="标的原文片段（用户原话，逐字保留，不做代码补全；最终证券识别由后端负责）")
    option_type: CandidateScalar | None = Field(default=None, alias="optionType", description="期权类型：欧式看涨 / 参与型看涨 / 雪球；未明确 → null")
    product_type: CandidateScalar | None = Field(default=None, alias="productType", description="单笔订单的产品类型字符串，如 EUROPEAN_VANILLA / PARTICIPATORY / AUTOCALL；仅取本次明确提供的类型，不从期权名称推导，不与消息意图写回的整数分类混淆")
    #: 期限，"XM" 格式（如 "1M"/"12M"）
    tenor: CandidateScalar | None = Field(default=None, description="期限，XM 格式（如 1M / 12M）；年 × 12 折算为月")
    #: 行权价格百分比（数字，不带 %，如 100 / 95 / 103.5）
    strike_percentage: CandidateScalar | None = Field(default=None, alias="strikePercentage", description="行权价百分比，纯数字不带 %（如 100 / 95 / 103.5）")
    premium_rate_pct: CandidateScalar | None = Field(default=None, alias="premiumRatePct", description="本次明确提供的期权费率百分数，6.88 表示 6.88%；不换算为 0.0688，不回填引用或历史报价；未提供为 null")
    #: 名义本金（字符串数字，如 "1000000"）
    notional_amount: CandidateScalar | None = Field(default=None, alias="notionalAmount", description="名义本金，字符串数字（如 \"1000000\"）")
    #: 参与率（百分比数字 0-100）
    participation_rate: CandidateScalar | None = Field(default=None, alias="participationRate", description="参与率，百分比数字 0-100")
    order_type: CandidateScalar | None = Field(default=None, alias="orderType", description="本次明确的下单方式：市价单 / 限价单 / POV / TWAP。本次写出 POV11%、改POV12 等算法词连比例时，必须同时填写 POV，不能只输出比例，也不能因旧订单已经是 POV 而省略。本次未表达方式才为 null，不从旧卡片补齐")
    initial_order_instruction: CandidateScalar | None = Field(default=None, alias="initialOrderInstruction", description="本次建仓指令的连续原文片段，如 市价 / POV25 / 限价6.3；仅供展示，不代替执行参数，不从旧订单或各字段拼造；未提供为 null")
    limit_price: CandidateScalar | None = Field(default=None, alias="limitPrice", description="限价（限价单时的价格数字）")
    pov_ratio: CandidateScalar | None = Field(default=None, alias="povRatio", description="本次明确的 POV 跟量比例，使用百分数数字且不带 %；如 POV11% 为 11，改POV12 为 12。算法词本身还需在本次下单方式中表达，比例不能代替方式")
    #: TWAP 起止时间，"HH:MM" 格式（Dify DSL v2 重命名，原 algoStartTime/algoEndTime）
    twap_start_time: CandidateScalar | None = Field(default=None, alias="twapStartTime", description="TWAP 开始时间，HH:MM")
    twap_end_time: CandidateScalar | None = Field(default=None, alias="twapEndTime", description="TWAP 结束时间，HH:MM")
    short_name: CandidateScalar | None = Field(default=None, alias="shortName", description="交易对手名称（完整保留括号与特殊字符；用户回复选项字母时取对应完整名称）")
    # 雪球询价的显式结构参数，与 Java FinancialOrderOpenApiBaseSaveReqVO 同名。
    snowball_tenor_months: CandidateScalar | None = Field(default=None, alias="snowballTenorMonths", description="本次明确提供的雪球存续期月数；与 tenor 描述同一期限，但作为独立字段保留来源，不从旧订单或 tenor 自动补齐，不在代码中计算期限；未提供为 null")
    snowball_knock_in_lower_barrier_pct: CandidateScalar | None = Field(default=None, alias="snowballKnockInLowerBarrierPct", description="雪球敲入价格百分数；如85表示85%，仅取本次明确敲入值")
    snowball_knock_out_upper_barrier_pct: CandidateScalar | None = Field(default=None, alias="snowballKnockOutUpperBarrierPct", description="雪球敲出价格百分数；如100表示100%，不当作看涨行权价列表")
    snowball_margin_percentage_pct: CandidateScalar | None = Field(default=None, alias="snowballMarginPercentagePct", description="本次明确指定的雪球保证金百分数；缺失为null")
    snowball_lock_in_period_months: CandidateScalar | None = Field(default=None, alias="snowballLockInPeriodMonths", description="本次明确指定的雪球锁定期月数；缺失为null")
    snowball_annualized_coupon_rate_pct: CandidateScalar | None = Field(default=None, alias="snowballAnnualizedCouponRatePct", description="本次明确指定的雪球年化票息百分数；缺失为null")
    snowball_absolute_coupon_rate_pct: CandidateScalar | None = Field(default=None, alias="snowballAbsoluteCouponRatePct", description="本次明确指定的雪球绝对返息百分数；缺失为null")
    snowball_features_text: CandidateScalar | None = Field(default=None, alias="snowballFeaturesText", description="雪球其它特性原文，完整保留；未提供为null")


class OptionOrderItemWithFastExec(OptionOrderItem):
    """期权接口参数及本次明确的快速执行意图；所有动作共用字段，缺省不补值。"""

    #: 是否最大跟量（下游最大跟量公共 prompt 判定结果）
    has_fast_execution_intent: CandidateScalar | None = Field(default=None, alias="hasFastExecutionIntent", description="本次明确要求最大跟量或快速执行为 true；明确否定为 false；未提及必须为 null，不能默认 false；非 null 时同样必须提供字段证据")






# ============================================================
# 各节点输出容器（1 意图 : 1 节点 : 1 容器，Dify DSL v2 一一对应）
# ============================================================


class OptionInquiryParams(WireModel):
    """状态中的询价订单列表；值已由唯一模型请求提取，代码不再归一化。"""

    model_config = ConfigDict(extra="forbid")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；仅填本节点相关字段，其余 null")


class OptionPlaceParams(WireModel):
    """option.extract_place 节点输出（place_order_from_quote，请求下单）。"""

    model_config = ConfigDict(extra="forbid")

    order_list: list[OptionOrderItemWithFastExec] = Field(alias="orderList", default_factory=list, description="下单条目列表（含 hasFastExecutionIntent）；仅填本节点相关字段，其余 null")


class OptionConfirmPlaceParams(WireModel):
    """option.extract_confirm_place 节点输出（confirm_order，确认下单）。"""

    model_config = ConfigDict(extra="forbid")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；仅填本节点相关字段，其余 null")


__all__ = [
    "OptionIntentType",
    "OptionOrderType",
    "OptionContractType",
    "OptionOrderItem",
    "OptionOrderItemWithFastExec",
    "OptionInquiryParams",
    "OptionPlaceParams",
    "OptionConfirmPlaceParams",
]
