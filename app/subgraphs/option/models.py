"""option 子图的 Pydantic Output 模型。

字段命名对齐 Java enum `stockOptionIntentionType`，但仅保留 10 个 option
基础意图——6 个 close_order_* 归 close 子图（ADR 0011 二次修订）。

LLM 输出统一用 `type` 字段（与 Dify 原 prompt 约定一致）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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

    model_config = ConfigDict(extra="forbid")

    type: OptionIntentType


__all__ = ["OptionIntentType", "OptionIntentOutput"]
