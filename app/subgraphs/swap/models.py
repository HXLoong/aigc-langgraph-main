"""swap 子图的 Pydantic Output 模型。

字段命名严格对齐 Java enum `SwapIntentionType`（7 值，ADR 0001 D2）。
LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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


class SwapIntentOutput(BaseModel):
    """swap.intent 节点的 LLM 输出 schema。

    与 `app/prompts/swap/intent.md` 的输出契约一致（字段名 `type`）。
    """

    model_config = ConfigDict(extra="forbid")

    type: SwapIntentType


__all__ = ["SwapIntentType", "SwapIntentOutput"]
