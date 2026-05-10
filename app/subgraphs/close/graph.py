"""close 子图编译入口（骨架阶段）。

骨架阶段路径：
    START → close.intent → close.todo (占位) → END

后续每个节点 PR 添加：holding_query / place_close / confirm_close /
cancel_close / confirm_cancel / query_status（共 6 个）。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.close.intent import close_intent


@safe_node
async def close_todo(state: AgentState) -> dict[str, Any]:
    """占位节点：M2 后续 PR 替换为真节点。

    函数名与 trace.node 一致避免 @safe_node 重复加 trace。
    """
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="close_todo",
                decision=f"not_implemented_yet:intent={intent}",
            )
        ]
    }


def build_close_graph() -> CompiledStateGraph:
    """构建 close 子图（骨架阶段：intent + todo 占位）。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("close_intent", close_intent)
    g.add_node("close_todo", close_todo)
    g.add_edge(START, "close_intent")
    g.add_edge("close_intent", "close_todo")
    g.add_edge("close_todo", END)
    return g.compile()


__all__ = ["build_close_graph"]
