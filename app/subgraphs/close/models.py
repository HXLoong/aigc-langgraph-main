"""close 子图的 Pydantic Output 模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.wire_model import WireModel

# ============================================================
# 意图分类（close.intent）
# ============================================================


#: close 子图处理的 7 个意图（6 个 close_order_* + unknown）
CloseIntentType = Literal[
    "close_order_query",  # 平仓查询（持仓查询、按品种查询）
    "close_order_order_query",  # 平仓订单查询（按订单号查状态）
    "close_order_request",  # 平仓请求下单
    "close_order_confirm",  # 确认平仓
    "close_order_cancel_request",  # 平仓请求撤单
    "close_order_cancel_confirm",  # 平仓确认撤单
    "unknown_intent",
]


class CloseIntentOutput(BaseModel):
    """close.intent 节点的 LLM 输出 schema。"""

    model_config = ConfigDict(extra="ignore")

    type: CloseIntentType


# ============================================================
# 持仓查询参数（close.holding_query）
# ============================================================


#: 标的类型枚举（对齐 Java InsFamily）
InsFamily = Literal["EQUITY", "INDEX", "FUND", "FUTURE"]

#: 期权合约类型枚举（对齐 Java ContractType）
ContractType = Literal[
    "EUROPEAN_VANILLA",  # 欧式
    "AUTOCALL",  # 雪球
    "PARTICIPATORY",  # 参与型看涨
    "AIRBAG",  # 安全气囊
]


class HoldingQueryParams(WireModel):
    """close.holding_query 节点的 LLM 输出 schema（与 Dify holding_query.md 字段对齐）。

    驼峰命名匹配 Java DTO；`closeable_only` 是 snake_case 例外（与 prompt 一致）。
    """

    model_config = ConfigDict(extra="ignore")

    closeable_only: bool
    internal_trade_id_list: list[str] = Field(alias="internalTradeIdList", default_factory=list)
    key_ctpty_id_list: list[int] = Field(alias="keyCtptyIdList", default_factory=list)
    underlying_ins_name_list: list[str] = Field(alias="underlyingInsNameList", default_factory=list)
    underlying_ins_id_list: list[str] = Field(alias="underlyingInsIdList", default_factory=list)
    ins_family_list: list[InsFamily] = Field(alias="insFamilyList", default_factory=list)
    contract_type_list: list[ContractType] = Field(alias="contractTypeList", default_factory=list)


# ============================================================
# 确认平仓参数（close.confirm_close）
# ============================================================


class ConfirmCloseParams(WireModel):
    """close.confirm_close 节点 LLM 输出（与 Dify confirm_close.md 字段对齐）。

    字段名 confirmOrderNoList 驼峰对齐 Java DTO。空列表表示"引用消息中没有
    CO- 订单号 或 用户指定订单未匹配"。
    """

    model_config = ConfigDict(extra="ignore")

    confirm_order_no_list: list[str] = Field(alias="confirmOrderNoList", default_factory=list)


# ============================================================
# 撤销平仓参数（close.cancel_close）
# ============================================================


class CancelCloseParams(WireModel):
    """close.cancel_close 节点 LLM 输出（与 Dify cancel_close.md 字段对齐）。

    字段名 cancelOrderNoList 驼峰对齐 Java DTO。
    """

    model_config = ConfigDict(extra="ignore")

    cancel_order_no_list: list[str] = Field(alias="cancelOrderNoList", default_factory=list)


# ============================================================
# 平仓下单参数（close.place_close）
# ============================================================


#: 平仓订单类型枚举（与 Dify place_close.md 输出值集一致）
ClosePriceType = Literal["市价单", "限价单", "POV", "TWAP"]


class CloseOrderItem(WireModel):
    """closeOrderList 中的单个平仓订单条目（9 字段）。

    与 Dify place_close.md JSON schema 完全对齐。allow null 在所有字段
    （Dify prompt 明确允许 null 表示"用户未提供"）。
    """

    model_config = ConfigDict(extra="ignore")

    order_id: str | None = Field(default=None, alias="orderId")
    internal_trade_id: str | None = Field(default=None, alias="internalTradeId")
    #: 平仓金额（字符串数字，"全部" 时由后端语义而非此字段）
    close_order_notional_delta: str | None = Field(default=None, alias="closeOrderNotionalDelta")
    close_order_type: ClosePriceType | None = Field(default=None, alias="closeOrderType")
    close_order_price: float | int | None = Field(default=None, alias="closeOrderPrice")
    close_order_pov_ratio: int | None = Field(default=None, alias="closeOrderPovRatio")
    #: TWAP 起始时间，格式 "HH:MM"
    close_order_algo_start_time: str | None = Field(default=None, alias="closeOrderAlgoStartTime")
    close_order_algo_end_time: str | None = Field(default=None, alias="closeOrderAlgoEndTime")
    confirm_full_close: bool | None = Field(default=None, alias="confirmFullClose")


class ClosePlaceParams(WireModel):
    """close.place_close 节点 LLM 输出。

    顶层结构 `{"closeOrderList": [...]}` 与 Dify prompt 输出契约一致。
    空列表表示"无可绑定订单"或"输入语义为空"。
    """

    model_config = ConfigDict(extra="ignore")

    close_order_list: list[CloseOrderItem] = Field(alias="closeOrderList", default_factory=list)


# ============================================================
# 确认撤单参数（close.confirm_cancel）
# ============================================================


class ConfirmCancelParams(WireModel):
    """close.confirm_cancel 节点 LLM 输出。"""

    model_config = ConfigDict(extra="ignore")

    confirm_cancel_order_no_list: list[str] = Field(alias="confirmCancelOrderNoList", default_factory=list)


# ============================================================
# 平仓订单查询参数（close.query_status）
# ============================================================


class QueryStatusParams(WireModel):
    """close.query_status 节点 LLM 输出。"""

    model_config = ConfigDict(extra="ignore")

    query_order_no_list: list[str] = Field(alias="queryOrderNoList", default_factory=list)


__all__ = [
    "CloseIntentType",
    "CloseIntentOutput",
    "InsFamily",
    "ContractType",
    "HoldingQueryParams",
    "ConfirmCloseParams",
    "CancelCloseParams",
    "ClosePriceType",
    "CloseOrderItem",
    "ClosePlaceParams",
    "ConfirmCancelParams",
    "QueryStatusParams",
]
