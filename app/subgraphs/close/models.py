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


__all__ = [
    "CloseIntentType",
    "CloseIntentOutput",
    "InsFamily",
    "ContractType",
    "HoldingQueryParams",
]
