"""close 子图编译入口。

ADR 0001 D6 + grill-with-docs。

★ close 子图所有 7 节点真节点全部到位（intent + 6 真节点）：

    START → close_intent → [route_by_intent]
        → close_holding_query   (close_order_query)
        → close_place_close     (close_order_request)         ← P0 核心
        → close_confirm_close   (close_order_confirm)
        → close_cancel_close    (close_order_cancel_request)
        → close_confirm_cancel  (close_order_cancel_confirm)
        → close_query_status    (close_order_order_query)
        → close_unknown         (unknown_intent / cascade 错误兜底)
        → END

注：原 close_todo 占位节点已删除（所有真节点到位）。仅保留 close_unknown
处理 unknown_intent + cascade 防御场景。
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, SubgraphOutput, TraceEntry
from app.subgraphs.close.cancel_close import close_cancel_close
from app.subgraphs.close.confirm_cancel import close_confirm_cancel
from app.subgraphs.close.confirm_close import close_confirm_close
from app.subgraphs.close.holding_query import close_holding_query
from app.subgraphs.close.intent import close_intent
from app.subgraphs.close.place_close import build_place_close_graph
from app.subgraphs.close.query_status import close_query_status


@safe_node
async def close_unknown(state: AgentState) -> dict[str, Any]:
    """unknown_intent + cascade 错误兜底节点。

    替代原 close_todo 占位（close 子图所有真节点已实施）。仍保留以处理：
    - LLM 判 unknown_intent
    - intent 节点失败后的 cascade 防御目的地
    """
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="close_unknown",
                decision=f"unhandled_intent={intent}",
            )
        ]
    }


#: intent → 真节点 key 路由表（close 子图全 6 个 close_order_* 意图全覆盖）
_INTENT_TO_NODE: dict[str, str] = {
    "close_order_query": "close_holding_query",
    "close_order_request": "close_place_close",
    "close_order_confirm": "close_confirm_close",
    "close_order_cancel_request": "close_cancel_close",
    "close_order_cancel_confirm": "close_confirm_cancel",
    "close_order_order_query": "close_query_status",
}


def _route_after_close_intent(state: AgentState) -> str:
    """close.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "close_unknown"
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "close_unknown")


def build_close_graph() -> CompiledStateGraph:
    """构建 close 子图（7/7 真节点全部到位）。"""
    g: StateGraph = StateGraph(AgentState, output_schema=SubgraphOutput)
    g.add_node("close_intent", close_intent)
    g.add_node("close_holding_query", close_holding_query)
    # ADR 0024 重构 5：place_close 是子图（parse → fetch → extract → normalize → validate → submit/reject）
    g.add_node("close_place_close", build_place_close_graph())
    g.add_node("close_confirm_close", close_confirm_close)
    g.add_node("close_cancel_close", close_cancel_close)
    g.add_node("close_confirm_cancel", close_confirm_cancel)
    g.add_node("close_query_status", close_query_status)
    g.add_node("close_unknown", close_unknown)

    g.add_edge(START, "close_intent")
    g.add_conditional_edges(
        "close_intent",
        _route_after_close_intent,
        {
            "close_holding_query": "close_holding_query",
            "close_place_close": "close_place_close",
            "close_confirm_close": "close_confirm_close",
            "close_cancel_close": "close_cancel_close",
            "close_confirm_cancel": "close_confirm_cancel",
            "close_query_status": "close_query_status",
            "close_unknown": "close_unknown",
        },
    )
    for n in (
        "close_holding_query",
        "close_place_close",
        "close_confirm_close",
        "close_cancel_close",
        "close_confirm_cancel",
        "close_query_status",
        "close_unknown",
    ):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_close_graph"]
