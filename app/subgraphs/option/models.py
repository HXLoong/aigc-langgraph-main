"""option 子图的 Pydantic Output 模型。

字段命名对齐 Java enum `stockOptionIntentionType`，但仅保留 10 个 option
基础意图——6 个 close_order_* 归 close 子图（ADR 0011 二次修订）。

LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: option 子图处理的 10 个基础意图（不含 close_order_*）
OptionIntentType = Literal[
    "new_inquiry",
    "place_order_from_quote",
    "request_modify_order",
    "request_cancel_order",
    "cancel_order_request",
    "confirm_order",
    "confirm_cancel_order",
    "confirm_modify_order",
    "query_order_status",
    "unknown_intent",
]


class OptionIntentOutput(BaseModel):
    """option.intent 节点的 LLM 输出 schema。

    与 `app/prompts/option/intent.md`（ADR 0011 拆分后的独立分类 prompt）
    输出契约一致（字段名 `type`）。
    """

    model_config = ConfigDict(extra="ignore")

    type: OptionIntentType


# ============================================================
# 下单/改单参数（option.extract_place_or_modify）
# ============================================================


#: 期权下单订单类型枚举
OptionOrderType = Literal["市价单", "限价单", "POV", "TWAP"]


class OptionOrderItem(BaseModel):
    """orderList 中的单个订单条目（与 Dify 拆分版 prompt 对齐）。

    orderId 为可选的原单号，其余字段也全 Optional——LLM 仅提取用户提供的，
    未提供字段保持 null（与 close.place_close 同模式）。
    """

    model_config = ConfigDict(extra="ignore")

    #: Q- 开头的询价单号
    orderId: str | None = None
    #: 保留询价期限补充，供 Java 在需要时纠正意图并合并原单参数。
    tenor: str | None = None
    orderType: OptionOrderType | None = None
    limitPrice: float | int | None = None
    povRatio: float | int | None = None
    #: 名义本金（字符串数字，如 "1000000"）
    notionalAmount: str | None = None
    shortName: str | None = None
    #: TWAP 起始时间，格式 "HH:MM"
    algoStartTime: str | None = None
    algoEndTime: str | None = None


class OptionPlaceOrModifyParams(BaseModel):
    """option.extract_place_or_modify 节点 LLM 输出。

    结构与 close.place_close 类似：顶层 orderList 列表，每元素含订单参数。
    适用于 place_order_from_quote + request_modify_order 两个意图（共用 schema，
    靠 expected_action 区分；本骨架版 expected_action 由调用方根据 intent 推导）。
    """

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItem] = Field(default_factory=list)


# ============================================================
# 询价参数（option.extract_inquiry）
# ============================================================


#: 期权类型枚举（与 Dify intent_extract.md 用词对齐）
OptionContractType = Literal[
    "欧式看涨",
    "欧式看跌",
    "雪球",
    "气囊",
    "参与型看涨",
]


class OptionInquiryItem(BaseModel):
    """询价 orderList 中的单元素。

    LLM 提取自然语言不做标的标准化——`stockCode` 是用户原话片段；
    标准 wind 代码由调用方通过 ticker resolver 写入 state['tickers']。
    """

    model_config = ConfigDict(extra="ignore")

    #: 补参时传原 Q- 询价单号；首次询价未提供时为 None。
    orderId: str | None = None  # noqa: N815 - Java DTO 字段名
    stockCode: str | None = None
    optionType: OptionContractType | None = None
    tenor: str | None = None
    strikePercentage: float | int | None = None
    notionalAmount: float | int | None = None
    participationRate: float | int | None = None


class OptionInquiryParams(BaseModel):
    """option.extract_inquiry 节点 LLM 输出。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionInquiryItem] = Field(default_factory=list)


# ============================================================
# 撤单 / 确认 / 查询参数（option.extract_cancel / extract_confirm / extract_query）
#
# 三个节点输出共用 schema：仅含 orderList[orderId]。
# 上游 intent 节点决定调用哪个节点，下游业务根据 intent 区分行为。
# ============================================================


class OptionOrderRefItem(BaseModel):
    """轻量订单引用（仅 orderId，对齐 Dify cancel/confirm/query 输出）。"""

    model_config = ConfigDict(extra="ignore")

    orderId: str


class OptionExtractCancelParams(BaseModel):
    """option.extract_cancel 输出（cancel_order_request + request_cancel_order 合并）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderRefItem] = Field(default_factory=list)


class OptionExtractConfirmParams(BaseModel):
    """option.extract_confirm 输出（confirm_order + confirm_cancel_order +
    confirm_modify_order 合并版，靠 expected_action 区分子意图）。
    """

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderRefItem] = Field(default_factory=list)


class OptionExtractQueryParams(BaseModel):
    """option.extract_query 输出（query_order_status）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderRefItem] = Field(default_factory=list)


__all__ = [
    "OptionIntentType",
    "OptionIntentOutput",
    "OptionOrderType",
    "OptionOrderItem",
    "OptionPlaceOrModifyParams",
    "OptionContractType",
    "OptionInquiryItem",
    "OptionInquiryParams",
    "OptionOrderRefItem",
    "OptionExtractCancelParams",
    "OptionExtractConfirmParams",
    "OptionExtractQueryParams",
]
