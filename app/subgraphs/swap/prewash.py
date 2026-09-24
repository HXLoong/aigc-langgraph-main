"""swap.prewash · 互换开仓-前置清洗（Dify code 节点 1:1 移植）。

递归清洗 LLM 脏值：字面量 "null" 字符串（大小写不敏感、去首尾空白）→ None；
list 中被清成 None 的元素丢弃；dict 递归清洗。只清洗 orderList，顶层字段
（如 type）不清洗——清成 None 会触发后端 `@NotBlank` 裸 400，保留原值更安全。

源自 Dify「互换开仓-前置清洗」code 节点（Dify 资产已冻结于 tag dify-assets-frozen-20260917，ADR 0024 D1），在
`call_swap_backend`（backend.py）里对所有 6 个意图统一调用一次，对应 Dify
「模型数据聚合 → 互换开仓-前置清洗 → 互换开仓」的单一清洗落点。
"""
from __future__ import annotations

from typing import Any, cast

from app.domain.sanitize import DEFAULT_NULL_LITERALS, strip_null_literals


def sanitize_order_list(
    order_list: list[dict[str, Any]] | None,
    null_literals: frozenset[str] = DEFAULT_NULL_LITERALS,
) -> list[dict[str, Any]]:
    """清洗 orderList：字面量 "null" 字符串 → None，list 中的 None 元素丢弃。

    Args:
        order_list: swap.place_order / confirm / cancel / query_order 产出的订单列表
        null_literals: 视为 "空值" 的字符串字面量集合（小写比较）

    Returns:
        清洗后的新 order_list（不修改入参）
    """
    return cast(list[dict[str, Any]], strip_null_literals(order_list or [], null_literals))


__all__ = ["sanitize_order_list"]
