"""option 子图编译入口。

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

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.retry import add_io_node
from app.graph.state import AgentState, SubgraphOutput
from app.subgraphs.common import add_intent_dispatch, intent_router, make_unknown_node
from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.extract_cancel_place import option_extract_cancel_place
from app.subgraphs.option.extract_confirm_cancel import option_extract_confirm_cancel
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.extract_inquiry import build_inquiry_graph
from app.subgraphs.option.extract_place import option_extract_place
from app.subgraphs.option.extract_query import option_extract_query
from app.subgraphs.option.intent import option_intent

#: unknown_intent + cascade 错误兜底节点
option_unknown = make_unknown_node("option_unknown")

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

#: option.intent 后路由：cascade 防御 + intent 分发
_route_after_option_intent = intent_router(_INTENT_TO_NODE, "option_unknown")


def build_option_graph() -> CompiledStateGraph[AgentState, None, AgentState, SubgraphOutput]:
    """构建 option 子图（7 意图 : 7 真节点一一对应）。"""
    g: StateGraph[AgentState, None, AgentState, SubgraphOutput] = StateGraph(AgentState, output_schema=SubgraphOutput)
    add_io_node(g, "option_intent", option_intent)
    g.add_node("option_extract_inquiry", build_inquiry_graph())  # 子图原生嵌入（ADR 0024 D3）
    g.add_node("option_extract_place", option_extract_place)
    g.add_node("option_extract_confirm_place", option_extract_confirm_place)
    g.add_node("option_extract_cancel_place", option_extract_cancel_place)
    g.add_node("option_extract_cancel", option_extract_cancel)
    g.add_node("option_extract_confirm_cancel", option_extract_confirm_cancel)
    add_io_node(g, "option_extract_query", option_extract_query)
    g.add_node("option_unknown", option_unknown)

    g.add_edge(START, "option_intent")
    targets = add_intent_dispatch(
        g, "option_intent", _route_after_option_intent, _INTENT_TO_NODE, "option_unknown",
    )
    for n in targets:
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_option_graph"]
