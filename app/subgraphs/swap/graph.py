"""互换业务子图：消费联合解析，确定性选择候选并执行单一业务动作。"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.retry import add_io_node
from app.graph.state import AgentState, SubgraphOutput
from app.subgraphs.common import add_intent_dispatch, intent_router, make_unknown_node
from app.subgraphs.request_boundary import after_clean, after_prepare
from app.subgraphs.swap.apply_picks import swap_apply_picks
from app.subgraphs.swap.backend import swap_clean_request, swap_query_backend, swap_submit
from app.subgraphs.swap.cancel import swap_cancel
from app.subgraphs.swap.confirm import swap_confirm
from app.subgraphs.swap.intent import swap_intent
from app.subgraphs.swap.place_order import build_place_graph, swap_place_order_submit
from app.subgraphs.swap.query_order import swap_query_order

swap_unknown = make_unknown_node("swap_unknown")
_INTENT_TO_NODE = {
    "place_order_request": "swap_place_order", "cancel_order_request": "swap_cancel",
    "confirm_order": "swap_confirm", "confirm_cancel_order": "swap_confirm",
    "confirm_modify_order": "swap_confirm", "query_order_status": "swap_query_order",
}
_route_after_swap_intent = intent_router(_INTENT_TO_NODE, "swap_unknown")


def _route_after_place_order(state: AgentState) -> str:
    """参数准备错误时结束；候选选择使用同一次模型的指针。"""
    return "swap_unknown" if state.get("error") or state.get("reply_text") else "swap_apply_picks"


def _route_after_apply_picks(state: AgentState) -> str:
    """选择或字段锁定冲突时不提交整批订单。"""
    return "swap_unknown" if state.get("error") else "swap_place_order_submit"


def build_swap_graph() -> CompiledStateGraph[AgentState, None, AgentState, SubgraphOutput]:
    """保留原生产品边界；仅独立后端查询挂 RetryPolicy。"""
    graph = StateGraph(AgentState, output_schema=SubgraphOutput)
    graph.add_node("swap_intent", swap_intent)
    graph.add_node("swap_place_order", build_place_graph())
    graph.add_node("swap_apply_picks", swap_apply_picks)
    graph.add_node("swap_place_order_submit", swap_place_order_submit)
    graph.add_node("swap_confirm", swap_confirm)
    graph.add_node("swap_cancel", swap_cancel)
    graph.add_node("swap_query_order", swap_query_order)
    graph.add_node("swap_unknown", swap_unknown)
    graph.add_edge(START, "swap_intent")
    add_intent_dispatch(graph, "swap_intent", _route_after_swap_intent, _INTENT_TO_NODE, "swap_unknown")
    graph.add_conditional_edges("swap_place_order", _route_after_place_order, ["swap_apply_picks", "swap_unknown"])
    graph.add_conditional_edges("swap_apply_picks", _route_after_apply_picks, ["swap_place_order_submit", "swap_unknown"])
    for node in ("swap_place_order_submit", "swap_confirm", "swap_cancel", "swap_query_order", "swap_unknown"):
        graph.add_conditional_edges(node, after_prepare, {"done": END, "clean": "swap_clean_request"})
    graph.add_node("swap_clean_request", swap_clean_request)
    graph.add_node("swap_submit", swap_submit)
    add_io_node(graph, "swap_query_backend", swap_query_backend)
    graph.add_conditional_edges("swap_clean_request", after_clean,
                               {"done": END, "query": "swap_query_backend", "submit": "swap_submit"})
    graph.add_edge("swap_submit", END)
    graph.add_edge("swap_query_backend", END)
    return graph.compile()
