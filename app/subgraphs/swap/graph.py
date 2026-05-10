"""swap 子图编译入口。

ADR 0001 D6 + grill-with-docs 第 1 决策。

当前路径（含 place_order 真节点 · P0 核心）：
    START → swap_intent → [route_by_intent]
        → swap_place_order  (place_order_request)              ← P0 核心
        → swap_todo         (剩余 6 个意图 + unknown_intent)
        → END

后续 PR 添加：
- swap.confirm（合并 3 个原 confirm，靠 expected_action 区分）
- swap.cancel + swap.cancel_extract
- swap.query_order
- swap.place_order_image / swap.place_order_excel
- swap.image_recognize / swap.hand_to_share
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.swap.intent import swap_intent
from app.subgraphs.swap.place_order import swap_place_order


@safe_node
async def swap_todo(state: AgentState) -> dict[str, Any]:
    """占位节点：M2 后续 PR 替换为真节点。"""
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="swap_todo",
                decision=f"not_implemented_yet:intent={intent}",
            )
        ]
    }


#: intent → 真节点 key 路由表（新增真节点时只改这里）
_INTENT_TO_NODE: dict[str, str] = {
    "place_order_request": "swap_place_order",
}


def _route_after_swap_intent(state: AgentState) -> str:
    """swap.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "swap_todo"
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "swap_todo")


def build_swap_graph() -> CompiledStateGraph:
    """构建 swap 子图。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("swap_intent", swap_intent)
    g.add_node("swap_place_order", swap_place_order)
    g.add_node("swap_todo", swap_todo)

    g.add_edge(START, "swap_intent")
    g.add_conditional_edges(
        "swap_intent",
        _route_after_swap_intent,
        {
            "swap_place_order": "swap_place_order",
            "swap_todo": "swap_todo",
        },
    )
    for n in ("swap_place_order", "swap_todo"):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_swap_graph"]
