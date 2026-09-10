"""option 子图前置清洗 · 对齐 Dify code 节点「期权开仓-前置清洗」。

Dify 原节点（spec/code_nodes/期权开仓-前置清洗.py）在 LLM 输出的 `orderList`
送入「期权开仓」code 节点之前做一次脏值清洗：

- 字符串 "null"（大小写不敏感，去空白后比对）→ None
- 清洗后仍是 None 的 list 元素 → 从 list 中丢弃
- dict 递归清洗每个 value
- 只清洗 orderList；顶层 type/operate 不清洗（业务约定，清成 null 后端期权
  入口会 NPE，保留原字符串"null"落未知意图模板反而安全——本子图不涉及顶层
  type/operate 的 LLM 自由输出，故不适用，仅移植 orderList 清洗逻辑）

供 7 个 extract 节点在写 state 业务字段 / 调 `call_option_backend` 之前统一调用，
避免 LLM 偶发吐出字面量字符串 "null" 污染下游卡片渲染与后端请求。
"""
from __future__ import annotations

from typing import Any

#: 默认 null 字面量集合（对齐 Dify 环境变量 NULL_LITERALS 缺省值）
_DEFAULT_NULL_LITERALS: frozenset[str] = frozenset({"null"})


def _sanitize_value(value: Any, literals: frozenset[str]) -> Any:
    """递归清洗单个值：null 字面量字符串 → None；list 丢弃清成 None 的元素；dict 递归。"""
    if isinstance(value, str):
        return None if value.strip().lower() in literals else value
    if isinstance(value, list):
        return [
            cleaned
            for cleaned in (_sanitize_value(item, literals) for item in value)
            if cleaned is not None
        ]
    if isinstance(value, dict):
        return {k: _sanitize_value(v, literals) for k, v in value.items()}
    return value


def sanitize_order_list(
    order_list: list[dict[str, Any]] | None,
    null_literals: frozenset[str] = _DEFAULT_NULL_LITERALS,
) -> list[dict[str, Any]]:
    """清洗 orderList：每个订单 dict 内的字符串字段做 null 字面量清洗。

    与 Dify 原节点行为一致：订单条目本身不会被丢弃（dict 分支恒返回 dict，
    不会被外层 list 的 None 过滤器丢弃），只清洗其内部 value。
    """
    if not order_list:
        return []
    return [_sanitize_value(order, null_literals) for order in order_list]


__all__ = ["sanitize_order_list"]
