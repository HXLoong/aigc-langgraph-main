"""option 子图的 Pydantic Output 模型（Dify DSL v2 同步版）。

字段命名对齐 Java enum `stockOptionIntentionType`，但仅保留 7 个 option
基础意图（不含 close_order_* 归 close 子图；不再含 request_modify_order /
confirm_modify_order——期权无独立改单流程，改参数统一归 place_order_from_quote，
见 `app/prompts/option/intent.md` 规则1第7条）。

LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。

orderList item 结构在新 DSL 下 7 个 extract 节点共用同一份 13 字段 schema
（`OptionOrderItem`，来自 spec/llm_schemas.txt 对应节点 structured_output 的
实际【输出格式】字段集），仅 `place_order_from_quote`（下单）节点额外多一个
`hasFastExecutionIntent` 字段（`OptionOrderItemWithFastExec`）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class OptionIntentOutput(BaseModel):
    """option.intent 节点的 LLM 输出 schema。

    与 `app/prompts/option/intent.md`（Dify DSL v2 `期权-意图识别`，
    node_id=1755073106378）输出契约一致（字段名 `type`）。
    """

    model_config = ConfigDict(extra="ignore")

    type: OptionIntentType


# ============================================================
# orderList item 共用 schema（7 个 extract 节点共用，Dify DSL v2）
# ============================================================


#: 期权下单方式枚举
OptionOrderType = Literal["市价单", "限价单", "POV", "TWAP"]

#: 期权类型枚举（Dify DSL v2 收窄为 3 值，不再支持"欧式看跌"/"气囊"）
OptionContractType = Literal["欧式看涨", "参与型看涨", "雪球"]


class OptionOrderItem(BaseModel):
    """orderList 中的单个订单条目（7 个 extract 节点共用 13 字段 schema）。

    字段名 1:1 对齐 spec/llm_schemas.txt 中 `期权-节点-*` 系列 structured_output
    的实际【输出格式】：orderId / stockCode / optionType / tenor /
    strikePercentage / notionalAmount / participationRate / orderType /
    limitPrice / povRatio / twapStartTime / twapEndTime / shortName。
    全部字段 Optional——LLM 仅提取用户提供的，未提供字段保持 null。
    """

    model_config = ConfigDict(extra="ignore")

    orderId: str | None = None
    #: 标的原文（用户原话片段，标准化由 ticker resolver 负责）
    stockCode: str | None = None
    optionType: OptionContractType | None = None
    #: 期限，"XM" 格式（如 "1M"/"12M"）
    tenor: str | None = None
    #: 行权价格百分比（数字，不带 %，如 100 / 95 / 103.5）
    strikePercentage: float | int | None = None
    #: 名义本金（字符串数字，如 "1000000"）
    notionalAmount: str | None = None
    #: 参与率（百分比数字 0-100）
    participationRate: float | int | None = None
    orderType: OptionOrderType | None = None
    limitPrice: float | int | None = None
    povRatio: float | int | None = None
    #: TWAP 起止时间，"HH:MM" 格式（Dify DSL v2 重命名，原 algoStartTime/algoEndTime）
    twapStartTime: str | None = None
    twapEndTime: str | None = None
    shortName: str | None = None


class OptionOrderItemWithFastExec(OptionOrderItem):
    """`place_order_from_quote`（下单）节点专用：多一个 hasFastExecutionIntent 字段。"""

    #: 是否最大跟量（下游最大跟量公共 prompt 判定结果）
    hasFastExecutionIntent: bool | None = None


# ============================================================
# 各节点输出容器（1 意图 : 1 节点 : 1 容器，Dify DSL v2 一一对应）
# ============================================================


class OptionInquiryParams(BaseModel):
    """option.extract_inquiry 节点输出（new_inquiry，询价）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItem] = Field(default_factory=list)


class OptionPlaceParams(BaseModel):
    """option.extract_place 节点输出（place_order_from_quote，请求下单）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItemWithFastExec] = Field(default_factory=list)


class OptionConfirmPlaceParams(BaseModel):
    """option.extract_confirm_place 节点输出（confirm_order，确认下单）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItem] = Field(default_factory=list)


class OptionCancelPlaceParams(BaseModel):
    """option.extract_cancel_place 节点输出（cancel_order_request，取消下单）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItem] = Field(default_factory=list)


class OptionCancelParams(BaseModel):
    """option.extract_cancel 节点输出（request_cancel_order，请求撤单）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItem] = Field(default_factory=list)


class OptionConfirmCancelParams(BaseModel):
    """option.extract_confirm_cancel 节点输出（confirm_cancel_order，确认撤单）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItem] = Field(default_factory=list)


class OptionQueryParams(BaseModel):
    """option.extract_query 节点输出（query_order_status，查询订单状态）。"""

    model_config = ConfigDict(extra="ignore")

    orderList: list[OptionOrderItem] = Field(default_factory=list)


__all__ = [
    "OptionIntentType",
    "OptionIntentOutput",
    "OptionOrderType",
    "OptionContractType",
    "OptionOrderItem",
    "OptionOrderItemWithFastExec",
    "OptionInquiryParams",
    "OptionPlaceParams",
    "OptionConfirmPlaceParams",
    "OptionCancelPlaceParams",
    "OptionCancelParams",
    "OptionConfirmCancelParams",
    "OptionQueryParams",
]
