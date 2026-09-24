"""节点失败 cascade 防御工具（CLAUDE.md 核心原则第 9 条）。

任一节点写入 `state['error']`（被 @safe_node / add_io_node 捕获后）→ 下游 conditional
路由先用 `has_error` 判断并跳到兜底节点，禁止 cascade 失败。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def has_error(state: Mapping[str, Any]) -> bool:
    """判断 state 是否包含被 @safe_node 捕获的错误。"""
    return state.get("error") is not None


__all__ = ["has_error"]
