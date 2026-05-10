"""close 子图的 Pydantic Output 模型。

7 个意图：6 个 close_order_*（对齐 Java stockOptionIntentionType 中的平仓子集）
+ unknown_intent 兜底。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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


__all__ = ["CloseIntentType", "CloseIntentOutput"]
