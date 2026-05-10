"""option 子图编译入口。

ADR 0001 D6 + ADR 0011 二次修订 + grill-with-docs 第 1/2 决策。

当前路径（含 extract_place_or_modify 真节点）：
    START → option_intent → [route_by_intent]
        → option_extract_place_or_modify  (place_order_from_quote / request_modify_order)
        → option_todo                     (剩余 8 个意图 + unknown_intent)
        → END

后续 PR 添加 4 个 extract 节点：
- extract_inquiry（new_inquiry）— 含 ticker resolver 集成
- extract_cancel（cancel_order_request + request_cancel_order）
- extract_confirm（confirm_order + confirm_cancel_order + confirm_modify_order）
- extract_query（query_order_status）
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from app.subgraphs.option.extract_place_or_modify import (
    option_extract_place_or_modify,
)
from app.subgraphs.option.intent import option_intent


@safe_node
async def option_todo(state: AgentState) -> dict[str, Any]:
    """占位节点：M2 后续 PR 替换为 4 个 extract 真节点。"""
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="option_todo",
                decision=f"not_implemented_yet:intent={intent}",
            )
        ]
    }


#: intent → 真节点 key 路由表（新增真节点时只改这里）
_INTENT_TO_NODE: dict[str, str] = {
    "new_inquiry": "option_extract_inquiry",
    "place_order_from_quote": "option_extract_place_or_modify",
    "request_modify_order": "option_extract_place_or_modify",
}


def _route_after_option_intent(state: AgentState) -> str:
    """option.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "option_todo"
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "option_todo")


def build_option_graph() -> CompiledStateGraph:
    """构建 option 子图。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("option_intent", option_intent)
    g.add_node("option_extract_inquiry", option_extract_inquiry)
    g.add_node("option_extract_place_or_modify", option_extract_place_or_modify)
    g.add_node("option_todo", option_todo)

    g.add_edge(START, "option_intent")
    g.add_conditional_edges(
        "option_intent",
        _route_after_option_intent,
        {
            "option_extract_inquiry": "option_extract_inquiry",
            "option_extract_place_or_modify": "option_extract_place_or_modify",
            "option_todo": "option_todo",
        },
    )
    for n in (
        "option_extract_inquiry",
        "option_extract_place_or_modify",
        "option_todo",
    ):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_option_graph"]
