"""节点失败 cascade 防御工具。

CLAUDE.md 核心原则第 8 条 + grill-with-docs 2026-05-10 第 6 个决策。

任一节点写入 `state['error']`（被 @safe_node 捕获后）→ 下游 conditional 路由
通过 `with_cascade_guard` 跳到 fallback，禁止 cascade 失败。
"""
from __future__ import annotations

from collections.abc import Callable

from app.graph.state import AgentState


def has_error(state: AgentState) -> bool:
    """判断 state 是否包含被 @safe_node 捕获的错误。"""
    return state.get("error") is not None


def with_cascade_guard(
    next_node: str,
    fallback_node: str = "fallback",
) -> Callable[[AgentState], str]:
    """生成 LangGraph conditional_edges 路由函数。

    若 `state['error']` 存在 → 返回 `fallback_node`，否则返回 `next_node`。

    Example:
        g.add_conditional_edges(
            "swap.intent",
            with_cascade_guard("swap.place_order"),
            {"swap.place_order": "swap.place_order", "fallback": "fallback"},
        )
    """

    def router(state: AgentState) -> str:
        return fallback_node if has_error(state) else next_node

    return router


__all__ = ["has_error", "with_cascade_guard"]
