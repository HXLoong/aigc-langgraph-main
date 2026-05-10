"""close 子图编译入口。

ADR 0001 D6 + grill-with-docs。

当前路径：
    START → close_intent → [route_by_intent]
        → close_holding_query   (close_order_query)
        → close_confirm_close   (close_order_confirm)
        → close_cancel_close    (close_order_cancel_request)
        → close_todo            (剩余 3 个 close_order_* + unknown_intent)
        → END

后续 PR 添加：
- close_place_close（close_order_request，P0 核心）
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
from app.subgraphs.close.cancel_close import close_cancel_close
from app.subgraphs.close.confirm_close import close_confirm_close
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


#: 子图内 intent → 真节点 key 的路由表（新增真节点时只改这里）
_INTENT_TO_NODE: dict[str, str] = {
    "close_order_query": "close_holding_query",
    "close_order_confirm": "close_confirm_close",
    "close_order_cancel_request": "close_cancel_close",
}


def _route_after_close_intent(state: AgentState) -> str:
    """close.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "close_todo"  # 主图 cascade 防御接管
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "close_todo")


def build_close_graph() -> CompiledStateGraph:
    """构建 close 子图。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("close_intent", close_intent)
    g.add_node("close_holding_query", close_holding_query)
    g.add_node("close_confirm_close", close_confirm_close)
    g.add_node("close_cancel_close", close_cancel_close)
    g.add_node("close_todo", close_todo)

    g.add_edge(START, "close_intent")
    g.add_conditional_edges(
        "close_intent",
        _route_after_close_intent,
        {
            "close_holding_query": "close_holding_query",
            "close_confirm_close": "close_confirm_close",
            "close_cancel_close": "close_cancel_close",
            "close_todo": "close_todo",
        },
    )
    for n in (
        "close_holding_query",
        "close_confirm_close",
        "close_cancel_close",
        "close_todo",
    ):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_close_graph"]
