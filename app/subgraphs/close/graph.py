"""close 子图编译入口。

ADR 0001 D6：intent + 6 个意图节点 + close_unknown 兜底。

    START → close_intent → [route_by_intent]
        → close_holding_query   (close_order_query)
        → close_place_close     (close_order_request)         ← P0 核心
        → close_confirm_close   (close_order_confirm)
        → close_cancel_close    (close_order_cancel_request)
        → close_confirm_cancel  (close_order_cancel_confirm)
        → close_query_status    (close_order_order_query)
        → close_unknown         (unknown_intent / cascade 错误兜底)
        → END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.retry import add_io_node
from app.graph.state import AgentState, SubgraphOutput
from app.subgraphs.close.cancel_close import close_cancel_close
from app.subgraphs.close.confirm_cancel import close_confirm_cancel
from app.subgraphs.close.confirm_close import close_confirm_close
from app.subgraphs.close.holding_query import close_holding_query
from app.subgraphs.close.intent import close_intent
from app.subgraphs.close.place_close import build_place_close_graph
from app.subgraphs.close.query_status import close_query_status
from app.subgraphs.common import add_intent_dispatch, intent_router, make_unknown_node

#: unknown_intent + cascade 错误兜底节点（LLM 判 unknown_intent，或 intent 节点失败）
close_unknown = make_unknown_node("close_unknown")

#: intent → 真节点 key 路由表（close 子图全 6 个 close_order_* 意图全覆盖）
_INTENT_TO_NODE: dict[str, str] = {
    "close_order_query": "close_holding_query",
    "close_order_request": "close_place_close",
    "close_order_confirm": "close_confirm_close",
    "close_order_cancel_request": "close_cancel_close",
    "close_order_cancel_confirm": "close_confirm_cancel",
    "close_order_order_query": "close_query_status",
}

#: close.intent 后路由：cascade 防御 + intent 分发
_route_after_close_intent = intent_router(_INTENT_TO_NODE, "close_unknown")


def build_close_graph() -> CompiledStateGraph[AgentState, None, AgentState, SubgraphOutput]:
    """构建 close 子图（intent + 6 意图节点 + unknown 兜底）。"""
    g: StateGraph[AgentState, None, AgentState, SubgraphOutput] = StateGraph(AgentState, output_schema=SubgraphOutput)
    add_io_node(g, "close_intent", close_intent)
    add_io_node(g, "close_holding_query", close_holding_query)
    # ADR 0024 重构 5：place_close 是子图（parse → fetch → extract → normalize → validate → submit/reject）
    g.add_node("close_place_close", build_place_close_graph())
    g.add_node("close_confirm_close", close_confirm_close)
    g.add_node("close_cancel_close", close_cancel_close)
    g.add_node("close_confirm_cancel", close_confirm_cancel)
    add_io_node(g, "close_query_status", close_query_status)
    g.add_node("close_unknown", close_unknown)

    g.add_edge(START, "close_intent")
    targets = add_intent_dispatch(
        g, "close_intent", _route_after_close_intent, _INTENT_TO_NODE, "close_unknown",
    )
    for n in targets:
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_close_graph"]
