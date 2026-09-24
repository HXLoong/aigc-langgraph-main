"""LLM / 上游偶发输出的字面量 "null" 清洗（对齐 Dify NULL_LITERALS 语义）。

三个子图的前置清洗（option/sanitize、swap/prewash、close/aggregate）共用此递归核心，
各自只保留外层包装的历史差异。
"""
from __future__ import annotations

from typing import Any

#: Dify `NULL_LITERALS` 环境变量缺省值
DEFAULT_NULL_LITERALS: frozenset[str] = frozenset({"null"})


def strip_null_literals(value: Any, literals: frozenset[str] = DEFAULT_NULL_LITERALS) -> Any:
    """递归清洗：null 字面量字符串（去空白、小写比较）→ None；list 丢弃清成 None 的元素；dict 递归。"""
    if isinstance(value, str):
        return None if value.strip().lower() in literals else value
    if isinstance(value, list):
        return [c for c in (strip_null_literals(i, literals) for i in value) if c is not None]
    if isinstance(value, dict):
        return {k: strip_null_literals(v, literals) for k, v in value.items()}
    return value


__all__ = ["DEFAULT_NULL_LITERALS", "strip_null_literals"]
