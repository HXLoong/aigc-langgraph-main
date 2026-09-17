"""ConversationMemory 读取（ADR 0024 D2 / D4）。

`last_confirmed_params` 是跨轮持久化的"上一轮已确认业务对象"（写入点：主图
`remember_confirmed_params` 节点；ingest 不重置）。确认链路（确认下单 / 确认撤单 /
确认平仓）在用户**没有**引用消息、也**没有**点名单号时读它，而不是从空文本"重抽"出
orderId=null。显式引用 / 显式单号永远优先于记忆——记忆只补裸确认，不扩大操作范围。
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
