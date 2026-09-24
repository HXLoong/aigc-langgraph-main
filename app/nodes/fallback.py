"""fallback 节点：cascade 防御命中后的统一路由终点。

CLAUDE.md 核心原则第 8 条：任一节点 fail → 跳此节点 → render 输出友好回复。

本节点只写 trace 标记 fallback 触发；回复由 render 节点根据 `state['error']` 输出
不可达 / 缺上下文等专用提示，其余输出统一引导文案（`Settings.default_reply`）。
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
