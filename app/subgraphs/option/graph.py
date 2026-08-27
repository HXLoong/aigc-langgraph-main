"""option 子图编译入口（Dify DSL v2 迁移，分支 feature/dify-dsl-migration，P2 option 域）。

    START → option_intent → [route_by_intent]
        → option_extract_inquiry        (new_inquiry)
        → option_extract_place          (place_order_from_quote)
        → option_extract_confirm_place  (confirm_order)
        → option_extract_cancel_place   (cancel_order_request)
        → option_extract_cancel         (request_cancel_order)
        → option_extract_confirm_cancel (confirm_cancel_order)
        → option_extract_query          (query_order_status)
        → option_unknown                (unknown_intent + cascade 错误兜底)
        → END

7 个意图 : 7 个真节点一一对应（Dify DSL v2「期权-意图识别」8 枚举值，
unknown_intent 走兜底）。不再有 request_modify_order / confirm_modify_order
——期权无独立改单流程，对已有订单的参数修改统一归 place_order_from_quote。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.extract_cancel_place import option_extract_cancel_place
from app.subgraphs.option.extract_confirm_cancel import option_extract_confirm_cancel
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from app.subgraphs.option.extract_place import option_extract_place
from app.subgraphs.option.extract_query import option_extract_query
from app.subgraphs.option.intent import option_intent


@safe_node
async def option_unknown(state: AgentState) -> dict[str, Any]:
    """unknown_intent + cascade 错误兜底节点。"""
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="option_unknown",
                decision=f"unhandled_intent={intent}",
            )
        ]
    }


#: intent → 真节点 key 路由表（option 子图 7 个基础意图全覆盖，unknown 走 unknown 兜底）
_INTENT_TO_NODE: dict[str, str] = {
    "new_inquiry": "option_extract_inquiry",
    "place_order_from_quote": "option_extract_place",
    "confirm_order": "option_extract_confirm_place",
    "cancel_order_request": "option_extract_cancel_place",
    "request_cancel_order": "option_extract_cancel",
    "confirm_cancel_order": "option_extract_confirm_cancel",
    "query_order_status": "option_extract_query",
}


def _route_after_option_intent(state: AgentState) -> str:
    """option.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "option_unknown"
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "option_unknown")


def build_option_graph() -> CompiledStateGraph:
    """构建 option 子图（7 意图 : 7 真节点一一对应，Dify DSL v2）。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("option_intent", option_intent)
    g.add_node("option_extract_inquiry", option_extract_inquiry)
    g.add_node("option_extract_place", option_extract_place)
    g.add_node("option_extract_confirm_place", option_extract_confirm_place)
    g.add_node("option_extract_cancel_place", option_extract_cancel_place)
    g.add_node("option_extract_cancel", option_extract_cancel)
    g.add_node("option_extract_confirm_cancel", option_extract_confirm_cancel)
    g.add_node("option_extract_query", option_extract_query)
    g.add_node("option_unknown", option_unknown)

    g.add_edge(START, "option_intent")
    g.add_conditional_edges(
        "option_intent",
        _route_after_option_intent,
        {
            "option_extract_inquiry": "option_extract_inquiry",
            "option_extract_place": "option_extract_place",
            "option_extract_confirm_place": "option_extract_confirm_place",
            "option_extract_cancel_place": "option_extract_cancel_place",
            "option_extract_cancel": "option_extract_cancel",
            "option_extract_confirm_cancel": "option_extract_confirm_cancel",
            "option_extract_query": "option_extract_query",
            "option_unknown": "option_unknown",
        },
    )
    for n in (
        "option_extract_inquiry",
        "option_extract_place",
        "option_extract_confirm_place",
        "option_extract_cancel_place",
        "option_extract_cancel",
        "option_extract_confirm_cancel",
        "option_extract_query",
        "option_unknown",
    ):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_option_graph"]
