"""close 子图编译入口。

ADR 0001 D6 + grill-with-docs。

当前路径（含 holding_query 真节点）：
    START → close_intent → [route_by_intent]
        → close_holding_query  (close_order_query)
        → close_todo           (其余 5 个 close_order_* + unknown_intent)
        → END

后续 PR 添加：
- close_place_close（close_order_request）
- close_confirm_close（close_order_confirm）
- close_cancel_close（close_order_cancel_request）
- close_confirm_cancel（close_order_cancel_confirm）
- close_query_status（close_order_order_query）
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.close.holding_query import close_holding_query
from app.subgraphs.close.intent import close_intent


@safe_node
async def close_todo(state: AgentState) -> dict[str, Any]:
    """占位节点：M2 后续 PR 替换为真节点。"""
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="close_todo",
                decision=f"not_implemented_yet:intent={intent}",
            )
        ]
    }


def _route_after_close_intent(state: AgentState) -> str:
    """close.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "close_todo"  # 子图内不进 fallback（主图 cascade 已处理）
    intent = state.get("intent") or "unknown_intent"
    if intent == "close_order_query":
        return "close_holding_query"
    return "close_todo"


def build_close_graph() -> CompiledStateGraph:
    """构建 close 子图。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("close_intent", close_intent)
    g.add_node("close_holding_query", close_holding_query)
    g.add_node("close_todo", close_todo)

    g.add_edge(START, "close_intent")
    g.add_conditional_edges(
        "close_intent",
        _route_after_close_intent,
        {
            "close_holding_query": "close_holding_query",
            "close_todo": "close_todo",
        },
    )
    g.add_edge("close_holding_query", END)
    g.add_edge("close_todo", END)
    return g.compile()


__all__ = ["build_close_graph"]
