"""swap 子图编译入口（骨架阶段）。

ADR 0001 D6 + grill-with-docs 第 1 决策（节点为单位，子图首 PR 含骨架）。

骨架阶段路径：
    START → swap.intent → swap.todo (占位) → END

后续每个节点 PR 添加：
1. 新建 `app/subgraphs/swap/<node>.py`
2. 在 graph.py 中 add_node + 在 intent 后加 conditional 分支
3. 删除 swap.todo 占位（最后一个节点 PR 时）
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.swap.intent import swap_intent


@safe_node
async def swap_todo(state: AgentState) -> dict[str, Any]:
    """占位节点：M2 后续 PR 替换为真节点（place_order / cancel / confirm 等）。

    intent 路由后所有意图先到这里。后续 PR 在 intent 后加 conditional_edges
    分发到具体节点，同时删除本 stub。

    函数名与 trace.node 一致避免 @safe_node 重复加 trace。
    """
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="swap_todo",
                decision=f"not_implemented_yet:intent={intent}",
            )
        ]
    }


def build_swap_graph() -> CompiledStateGraph:
    """构建 swap 子图（骨架阶段：intent + todo 占位）。

    主图通过 `g.add_node("swap", build_swap_graph())` 嵌入。
    """
    g: StateGraph = StateGraph(AgentState)
    g.add_node("swap_intent", swap_intent)
    g.add_node("swap_todo", swap_todo)
    g.add_edge(START, "swap_intent")
    g.add_edge("swap_intent", "swap_todo")
    g.add_edge("swap_todo", END)
    return g.compile()


__all__ = ["build_swap_graph"]
