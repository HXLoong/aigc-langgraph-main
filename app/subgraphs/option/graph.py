"""option 子图编译入口。

ADR 0001 D6 + ADR 0011 二次修订 + grill-with-docs 第 1/2 决策。

★ option 子图 6/6 真节点全部到位（100%）：

    START → option_intent → [route_by_intent]
        → option_extract_inquiry          (new_inquiry)
        → option_extract_place_or_modify  (place_order_from_quote / request_modify_order)
        → option_extract_cancel           (cancel_order_request / request_cancel_order)
        → option_extract_confirm          (confirm_order / confirm_cancel_order /
                                           confirm_modify_order)
        → option_extract_query            (query_order_status)
        → option_unknown                  (unknown_intent + cascade 错误兜底)
        → END

注：原 option_todo 占位节点已删除（所有真节点到位）。仅保留 option_unknown
处理 unknown_intent + cascade 防御场景。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.extract_confirm import option_extract_confirm
from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from app.subgraphs.option.extract_place_or_modify import (
    option_extract_place_or_modify,
)
from app.subgraphs.option.extract_query import option_extract_query
from app.subgraphs.option.intent import option_intent


@safe_node
async def option_unknown(state: AgentState) -> dict[str, Any]:
    """unknown_intent + cascade 错误兜底节点（替代原 option_todo）。"""
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="option_unknown",
                decision=f"unhandled_intent={intent}",
            )
        ]
    }


#: intent → 真节点 key 路由表（option 子图 9 个意图全覆盖，unknown 走 unknown 兜底）
_INTENT_TO_NODE: dict[str, str] = {
    "new_inquiry": "option_extract_inquiry",
    "place_order_from_quote": "option_extract_place_or_modify",
    "request_modify_order": "option_extract_place_or_modify",
    "cancel_order_request": "option_extract_cancel",
    "request_cancel_order": "option_extract_cancel",
    "confirm_order": "option_extract_confirm",
    "confirm_cancel_order": "option_extract_confirm",
    "confirm_modify_order": "option_extract_confirm",
    "query_order_status": "option_extract_query",
}


def _route_after_option_intent(state: AgentState) -> str:
    """option.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "option_unknown"
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "option_unknown")


def build_option_graph() -> CompiledStateGraph:
    """构建 option 子图（6/6 真节点全部到位）。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("option_intent", option_intent)
    g.add_node("option_extract_inquiry", option_extract_inquiry)
    g.add_node("option_extract_place_or_modify", option_extract_place_or_modify)
    g.add_node("option_extract_cancel", option_extract_cancel)
    g.add_node("option_extract_confirm", option_extract_confirm)
    g.add_node("option_extract_query", option_extract_query)
    g.add_node("option_unknown", option_unknown)

    g.add_edge(START, "option_intent")
    g.add_conditional_edges(
        "option_intent",
        _route_after_option_intent,
        {
            "option_extract_inquiry": "option_extract_inquiry",
            "option_extract_place_or_modify": "option_extract_place_or_modify",
            "option_extract_cancel": "option_extract_cancel",
            "option_extract_confirm": "option_extract_confirm",
            "option_extract_query": "option_extract_query",
            "option_unknown": "option_unknown",
        },
    )
    for n in (
        "option_extract_inquiry",
        "option_extract_place_or_modify",
        "option_extract_cancel",
        "option_extract_confirm",
        "option_extract_query",
        "option_unknown",
    ):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_option_graph"]
