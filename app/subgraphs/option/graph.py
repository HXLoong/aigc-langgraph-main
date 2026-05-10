"""option 子图编译入口（骨架阶段）。

ADR 0001 D6 + ADR 0011 二次修订 + grill-with-docs 第 1/2 决策。

骨架阶段路径：
    START → option.intent → option.todo (占位) → END

后续每个 extract 节点 PR 添加：
1. 新建 `app/subgraphs/option/extract_<intent>.py`
2. 在 graph.py 中 add_node + 在 intent 后加 conditional 分支按 type 路由
3. 删除 option.todo 占位（最后一个 extract 节点 PR 时）
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.intent import option_intent


@safe_node
async def option_todo(state: AgentState) -> dict[str, Any]:
    """占位节点：M2 后续 PR 替换为真 extract 节点（5 个）。

    intent 路由后所有意图先到这里。后续 PR 在 intent 后加 conditional_edges
    按 type 分发到 5 个 extract，同时删除本 stub。

    函数名与 trace.node 一致避免 @safe_node 重复加 trace。
    """
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="option_todo",
                decision=f"not_implemented_yet:intent={intent}",
            )
        ]
    }


def build_option_graph() -> CompiledStateGraph:
    """构建 option 子图（骨架阶段：intent + todo 占位）。

    主图通过 `g.add_node("option", build_option_graph())` 嵌入。
    """
    g: StateGraph = StateGraph(AgentState)
    g.add_node("option_intent", option_intent)
    g.add_node("option_todo", option_todo)
    g.add_edge(START, "option_intent")
    g.add_edge("option_intent", "option_todo")
    g.add_edge("option_todo", END)
    return g.compile()


__all__ = ["build_option_graph"]
