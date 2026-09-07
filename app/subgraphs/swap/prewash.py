"""swap.prewash · 互换开仓-前置清洗（Dify code 节点 1:1 移植）。

递归清洗 LLM 脏值：字面量 "null" 字符串（大小写不敏感、去首尾空白）→ None；
list 中被清成 None 的元素丢弃；dict 递归清洗。只清洗 orderList，顶层字段
（如 type）不清洗——清成 None 会触发后端 `@NotBlank` 裸 400，保留原值更安全。

1:1 对照 `/private/tmp/.../spec/code_nodes/互换开仓-前置清洗.py`，在
`call_swap_backend`（backend.py）里对所有 6 个意图统一调用一次，对应 Dify
「模型数据聚合 → 互换开仓-前置清洗 → 互换开仓」的单一清洗落点。
"""
from __future__ import annotations

from typing import Any

#: Dify `NULL_LITERALS` 环境变量默认值（逗号分隔，缺省即 {"null"}）。
_DEFAULT_NULL_LITERALS = frozenset({"null"})


def _sanitize(value: Any, literals: frozenset[str]) -> Any:
    if isinstance(value, str):
        return None if value.strip().lower() in literals else value
    if isinstance(value, list):
        return [c for c in (_sanitize(i, literals) for i in value) if c is not None]
    if isinstance(value, dict):
        return {k: _sanitize(v, literals) for k, v in value.items()}
    return value


def sanitize_order_list(
    order_list: list[dict[str, Any]] | None,
    null_literals: frozenset[str] = _DEFAULT_NULL_LITERALS,
) -> list[dict[str, Any]]:
    """清洗 orderList：字面量 "null" 字符串 → None，list 中的 None 元素丢弃。

    Args:
        order_list: swap.place_order / confirm / cancel / query_order 产出的订单列表
        null_literals: 视为 "空值" 的字符串字面量集合（小写比较）

    Returns:
        清洗后的新 order_list（不修改入参）
    """
    return _sanitize(order_list or [], null_literals)


__all__ = ["sanitize_order_list"]
