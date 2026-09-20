"""ConversationMemory 的只读订单身份访问（ADR 0024 D2 / D4）。

last_confirmed_params 仍供跨轮上下文保留；2026-09-20 协议改造后，七条最终确认
路径只使用用户当前引用，不再调用此兼容读取函数补充订单号。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def memory_order_ids(state: Mapping[str, Any], product_type: str) -> list[str]:
    """上一轮已确认订单号；产品线不匹配或无记忆 → []。"""
    memory = state.get("last_confirmed_params") or {}
    if not isinstance(memory, dict) or memory.get("product_type") != product_type:
        return []
    return [oid for oid in (memory.get("order_ids") or []) if isinstance(oid, str) and oid]


__all__ = ["memory_order_ids"]
