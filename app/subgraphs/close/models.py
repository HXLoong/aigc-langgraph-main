"""close 子图的 Pydantic Output 模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(extra="forbid")

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


class HoldingQueryParams(BaseModel):
    """close.holding_query 节点的 LLM 输出 schema（与 Dify holding_query.md 字段对齐）。

    驼峰命名匹配 Java DTO；`closeable_only` 是 snake_case 例外（与 prompt 一致）。
    """

    model_config = ConfigDict(extra="forbid")

    closeable_only: bool
    internalTradeIdList: list[str] = Field(default_factory=list)
    keyCtptyIdList: list[int] = Field(default_factory=list)
    underlyingInsNameList: list[str] = Field(default_factory=list)
    underlyingInsIdList: list[str] = Field(default_factory=list)
    insFamilyList: list[InsFamily] = Field(default_factory=list)
    contractTypeList: list[ContractType] = Field(default_factory=list)


# ============================================================
# 确认平仓参数（close.confirm_close）
# ============================================================


class ConfirmCloseParams(BaseModel):
    """close.confirm_close 节点 LLM 输出（与 Dify confirm_close.md 字段对齐）。

    字段名 confirmOrderNoList 驼峰对齐 Java DTO。空列表表示"引用消息中没有
    CO- 订单号 或 用户指定订单未匹配"。
    """

    model_config = ConfigDict(extra="forbid")

    confirmOrderNoList: list[str] = Field(default_factory=list)


# ============================================================
# 撤销平仓参数（close.cancel_close）
# ============================================================


class CancelCloseParams(BaseModel):
    """close.cancel_close 节点 LLM 输出（与 Dify cancel_close.md 字段对齐）。

    字段名 cancelOrderNoList 驼峰对齐 Java DTO。
    """

    model_config = ConfigDict(extra="forbid")

    cancelOrderNoList: list[str] = Field(default_factory=list)


# ============================================================
# 平仓下单参数（close.place_close）
# ============================================================


#: 平仓订单类型枚举（与 Dify place_close.md 输出值集一致）
ClosePriceType = Literal["市价单", "限价单", "POV", "TWAP"]


class CloseOrderItem(BaseModel):
    """closeOrderList 中的单个平仓订单条目（9 字段）。

    与 Dify place_close.md JSON schema 完全对齐。allow null 在所有字段
    （Dify prompt 明确允许 null 表示"用户未提供"）。
    """

    model_config = ConfigDict(extra="forbid")

    orderId: str | None = None
    internalTradeId: str | None = None
    #: 平仓金额（字符串数字，"全部" 时由后端语义而非此字段）
    closeOrderNotionalDelta: str | None = None
    closeOrderType: ClosePriceType | None = None
    closeOrderPrice: float | int | None = None
    closeOrderPovRatio: int | None = None
    #: TWAP 起始时间，格式 "HH:MM"
    closeOrderAlgoStartTime: str | None = None
    closeOrderAlgoEndTime: str | None = None
    confirmFullClose: bool | None = None


class ClosePlaceParams(BaseModel):
    """close.place_close 节点 LLM 输出。

    顶层结构 `{"closeOrderList": [...]}` 与 Dify prompt 输出契约一致。
    空列表表示"无可绑定订单"或"输入语义为空"。
    """

    model_config = ConfigDict(extra="forbid")

    closeOrderList: list[CloseOrderItem] = Field(default_factory=list)


# ============================================================
# 确认撤单参数（close.confirm_cancel）
# ============================================================


class ConfirmCancelParams(BaseModel):
    """close.confirm_cancel 节点 LLM 输出。"""

    model_config = ConfigDict(extra="forbid")

    confirmCancelOrderNoList: list[str] = Field(default_factory=list)


# ============================================================
# 平仓订单查询参数（close.query_status）
# ============================================================


class QueryStatusParams(BaseModel):
    """close.query_status 节点 LLM 输出。"""

    model_config = ConfigDict(extra="forbid")

    queryOrderNoList: list[str] = Field(default_factory=list)


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
