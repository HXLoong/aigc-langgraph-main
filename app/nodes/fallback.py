"""fallback 节点：cascade 防御命中后的统一路由终点。

CLAUDE.md 核心原则第 8 条：任一节点 fail → 跳此节点 → render 输出友好回复。

Day 1 行为：仅写 trace 标记 fallback 触发。M2 阶段 render 节点会根据
`state['error']` 是否存在决定输出固定话术（"我没完全理解你的意思..."）
还是走业务回复 LLM。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry


@safe_node
async def fallback(state: AgentState) -> dict[str, Any]:
    """fallback 节点。

    职责：在 trace 中记录"由哪个节点失败触发了 fallback"，让 harness
    suspected_node 启发式可定位真正的问题节点（不是 fallback 自己）。
    """
    err = state.get("error")
    err_node = err.node if err else "no_error"
    return {
        "trace": [
            TraceEntry(
                node="fallback",
                decision=f"triggered_by:{err_node}",
            )
        ],
    }


__all__ = ["fallback"]
