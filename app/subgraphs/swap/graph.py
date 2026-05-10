"""swap 子图编译入口。

ADR 0001 D5/D6 + grill-with-docs 第 1 决策。

★ swap 子图主路由 7/7 意图全覆盖（5 个真节点 + 1 unknown 兜底）：

    START → swap_intent → [route_by_intent]
        → swap_place_order  (place_order_request)         ← P0 核心
        → swap_confirm      (confirm_order / confirm_cancel_order /
                             confirm_modify_order)        ← 合并版（ADR 0001 D5）
        → swap_cancel       (cancel_order_request)
        → swap_query_order  (query_order_status)
        → swap_unknown      (unknown_intent + cascade 错误兜底)
        → END

P2 辅助节点（不对应 intent，是 swap.place_order 的工具）后续 PR 实施：
- swap.place_order_image（图片输入）
- swap.place_order_excel（Excel 输入）
- swap.image_recognize（图片识别工具）
- swap.hand_to_share（互换分享）
- swap.cancel_extract（如未来需要双阶段撤单确认）
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.swap.cancel import swap_cancel
from app.subgraphs.swap.confirm import swap_confirm
from app.subgraphs.swap.intent import swap_intent
from app.subgraphs.swap.place_order import swap_place_order
from app.subgraphs.swap.query_order import swap_query_order


@safe_node
async def swap_unknown(state: AgentState) -> dict[str, Any]:
    """unknown_intent + cascade 错误兜底节点（替代原 swap_todo）。"""
    intent = state.get("intent") or "unknown_intent"
    return {
        "trace": [
            TraceEntry(
                node="swap_unknown",
                decision=f"unhandled_intent={intent}",
            )
        ]
    }


#: intent → 真节点 key 路由表（swap 子图 7 个意图全覆盖）
_INTENT_TO_NODE: dict[str, str] = {
    "place_order_request": "swap_place_order",
    "cancel_order_request": "swap_cancel",
    "confirm_order": "swap_confirm",
    "confirm_cancel_order": "swap_confirm",
    "confirm_modify_order": "swap_confirm",
    "query_order_status": "swap_query_order",
}


def _route_after_swap_intent(state: AgentState) -> str:
    """swap.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "swap_unknown"
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "swap_unknown")


def build_swap_graph() -> CompiledStateGraph:
    """构建 swap 子图（主路由 7/7 意图全覆盖）。"""
    g: StateGraph = StateGraph(AgentState)
    g.add_node("swap_intent", swap_intent)
    g.add_node("swap_place_order", swap_place_order)
    g.add_node("swap_confirm", swap_confirm)
    g.add_node("swap_cancel", swap_cancel)
    g.add_node("swap_query_order", swap_query_order)
    g.add_node("swap_unknown", swap_unknown)

    g.add_edge(START, "swap_intent")
    g.add_conditional_edges(
        "swap_intent",
        _route_after_swap_intent,
        {
            "swap_place_order": "swap_place_order",
            "swap_confirm": "swap_confirm",
            "swap_cancel": "swap_cancel",
            "swap_query_order": "swap_query_order",
            "swap_unknown": "swap_unknown",
        },
    )
    for n in (
        "swap_place_order",
        "swap_confirm",
        "swap_cancel",
        "swap_query_order",
        "swap_unknown",
    ):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_swap_graph"]
