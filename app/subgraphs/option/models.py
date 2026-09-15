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


class OptionIntentOutput(BaseModel):
    """option.intent 节点的 LLM 输出 schema。

    与 `app/prompts/option/intent.md`（Dify DSL v2 `期权-意图识别`，
    node_id=1755073106378）输出契约一致（字段名 `type`）。
    """

    model_config = ConfigDict(extra="ignore")

    type: OptionIntentType = Field(description="期权意图，取 8 个枚举值之一")


# ============================================================
# orderList item 共用 schema（7 个 extract 节点共用，Dify DSL v2）
# ============================================================


#: 期权下单方式枚举
OptionOrderType = Literal["市价单", "限价单", "POV", "TWAP"]

#: 期权类型枚举（Dify DSL v2 收窄为 3 值，不再支持"欧式看跌"/"气囊"）
OptionContractType = Literal["欧式看涨", "参与型看涨", "雪球"]


class OptionOrderItem(WireModel):
    """orderList 中的单个订单条目（7 个 extract 节点共用 13 字段 schema）。

    字段名 1:1 对齐 spec/llm_schemas.txt 中 `期权-节点-*` 系列 structured_output
    的实际【输出格式】：orderId / stockCode / optionType / tenor /
    strikePercentage / notionalAmount / participationRate / orderType /
    limitPrice / povRatio / twapStartTime / twapEndTime / shortName。
    全部字段 Optional——LLM 仅提取用户提供的，未提供字段保持 null。
    """

    model_config = ConfigDict(extra="ignore")

    order_id: str | None = Field(default=None, alias="orderId", description="订单号（Q-YYYYMMDD-XXXXXXXXXX），仅在用户或引用消息明确给出时填写，否则 null")
    #: 标的原文（用户原话片段，标准化由 ticker resolver 负责）
    stock_code: str | None = Field(default=None, alias="stockCode", description="标的原文片段（用户原话，逐字保留，不做代码补全；标准化由 ticker resolver 负责）")
    option_type: OptionContractType | None = Field(default=None, alias="optionType", description="期权类型：欧式看涨 / 参与型看涨 / 雪球；未明确 → null")
    #: 期限，"XM" 格式（如 "1M"/"12M"）
    tenor: str | None = Field(default=None, description="期限，XM 格式（如 1M / 12M）；年 × 12 折算为月")
    #: 行权价格百分比（数字，不带 %，如 100 / 95 / 103.5）
    strike_percentage: float | int | None = Field(default=None, alias="strikePercentage", description="行权价百分比，纯数字不带 %（如 100 / 95 / 103.5）")
    #: 名义本金（字符串数字，如 "1000000"）
    notional_amount: str | None = Field(default=None, alias="notionalAmount", description="名义本金，字符串数字（如 \"1000000\"）")
    #: 参与率（百分比数字 0-100）
    participation_rate: float | int | None = Field(default=None, alias="participationRate", description="参与率，百分比数字 0-100")
    order_type: OptionOrderType | None = Field(default=None, alias="orderType", description="下单方式：市价单 / 限价单 / POV / TWAP")
    limit_price: float | int | None = Field(default=None, alias="limitPrice", description="限价（限价单时的价格数字）")
    pov_ratio: float | int | None = Field(default=None, alias="povRatio", description="POV 跟量比例（数字，不带 %）")
    #: TWAP 起止时间，"HH:MM" 格式（Dify DSL v2 重命名，原 algoStartTime/algoEndTime）
    twap_start_time: str | None = Field(default=None, alias="twapStartTime", description="TWAP 开始时间，HH:MM")
    twap_end_time: str | None = Field(default=None, alias="twapEndTime", description="TWAP 结束时间，HH:MM")
    short_name: str | None = Field(default=None, alias="shortName", description="交易对手名称（完整保留括号与特殊字符；用户回复选项字母时取对应完整名称）")


class OptionOrderItemWithFastExec(OptionOrderItem):
    """`place_order_from_quote`（下单）节点专用：多一个 hasFastExecutionIntent 字段。"""

    #: 是否最大跟量（下游最大跟量公共 prompt 判定结果）
    has_fast_execution_intent: bool | None = Field(default=None, alias="hasFastExecutionIntent", description="是否最大跟量 / 快速执行语义（按 system 中 hasFastExecutionIntent 规则判定）")


# ============================================================
# 各节点输出容器（1 意图 : 1 节点 : 1 容器，Dify DSL v2 一一对应）
# ============================================================


class OptionInquiryParams(WireModel):
    """option.extract_inquiry 节点输出（new_inquiry，询价）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；多期限 / 多执行价展开为多条；仅填本节点相关字段，其余 null")


class OptionPlaceParams(WireModel):
    """option.extract_place 节点输出（place_order_from_quote，请求下单）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[OptionOrderItemWithFastExec] = Field(alias="orderList", default_factory=list, description="下单条目列表（含 hasFastExecutionIntent）；仅填本节点相关字段，其余 null")


class OptionConfirmPlaceParams(WireModel):
    """option.extract_confirm_place 节点输出（confirm_order，确认下单）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；多期限 / 多执行价展开为多条；仅填本节点相关字段，其余 null")


class OptionCancelPlaceParams(WireModel):
    """option.extract_cancel_place 节点输出（cancel_order_request，取消下单）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；多期限 / 多执行价展开为多条；仅填本节点相关字段，其余 null")


class OptionCancelParams(WireModel):
    """option.extract_cancel 节点输出（request_cancel_order，请求撤单）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；多期限 / 多执行价展开为多条；仅填本节点相关字段，其余 null")


class OptionConfirmCancelParams(WireModel):
    """option.extract_confirm_cancel 节点输出（confirm_cancel_order，确认撤单）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；多期限 / 多执行价展开为多条；仅填本节点相关字段，其余 null")


class OptionQueryParams(WireModel):
    """option.extract_query 节点输出（query_order_status，查询订单状态）。"""

    model_config = ConfigDict(extra="ignore")

    order_list: list[OptionOrderItem] = Field(alias="orderList", default_factory=list, description="订单条目列表；多期限 / 多执行价展开为多条；仅填本节点相关字段，其余 null")


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
