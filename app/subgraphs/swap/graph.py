"""swap 子图编译入口（DSL v2 迁移，2026-08）。

ADR 0001 D5/D6 + grill-with-docs 第 1 决策 + DSL v2「主干工作流」互换段拓扑。

★ swap 子图主路由 6/6 意图全覆盖（unknown_intent 走 swap_unknown 兜底）：

    START → swap_intent → [route_by_intent]
        → swap_place_order → [quote_content 非空且非 "null"?]
              ├─ 是 → (swap_select_counterparty ‖ swap_select_ticker) → swap_apply_picks
              │       → swap_place_order_submit
              └─ 否 → swap_recognize_fresh_counterparty → swap_place_order_submit
        → swap_confirm      (confirm_order / confirm_cancel_order /
                             confirm_modify_order，共用节点函数按 intent 切 prompt)
        → swap_cancel       (cancel_order_request)
        → swap_query_order  (query_order_status)
        → swap_unknown      (unknown_intent + cascade 错误兜底)
        → END

cascade 防御（CLAUDE.md 核心原则第 8 条）：place_order 分支每一段 conditional
都检查 `has_error`，任一环节（下单 / 全新对手识别 / 选择交易对手 / 选择标的）失败即跳
swap_unknown，不让错误 cascade 到后端提交。

DSL v2 相对旧 DSL 的变化：
- 手转股（hand_to_share）迭代链已从新 DSL 消失，整体删除（Dify 原节点已死）
- 新增 swap.select_counterparty / swap.select_ticker（互换-选择交易对手 /
  互换-选择标的）+ swap.place_order 内联的互换-规整引用补参摘要（quote_hints.py）
- 下单提交（互换开仓-前置清洗 → 互换开仓）从 swap.place_order 拆到独立的
  swap.place_order_submit，确保标的/对手候选覆盖已落地再提交

P2 辅助节点（不对应 intent，是 swap.place_order 的工具，按线上流量增量补）：
- swap.place_order_image（图片输入）
- swap.place_order_excel（Excel 输入）
- swap.image_recognize（图片识别工具）
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.retry import add_io_node
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, SubgraphOutput, TraceEntry
from app.subgraphs.swap.apply_picks import swap_apply_picks
from app.subgraphs.swap.cancel import swap_cancel
from app.subgraphs.swap.confirm import swap_confirm
from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty
from app.subgraphs.swap.intent import swap_intent
from app.subgraphs.swap.multimodal import swap_excel_order, swap_image_order
from app.subgraphs.swap.place_order import build_place_graph, swap_place_order_submit
from app.subgraphs.swap.query_order import swap_query_order
from app.subgraphs.swap.select_counterparty import swap_select_counterparty
from app.subgraphs.swap.select_ticker import swap_select_ticker


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


#: intent → 真节点 key 路由表（swap 子图 6 个真实意图全覆盖，unknown_intent 走兜底）
_INTENT_TO_NODE: dict[str, str] = {
    "place_order_request": "swap_place_order",
    "cancel_order_request": "swap_cancel",
    "confirm_order": "swap_confirm",
    "confirm_cancel_order": "swap_confirm",
    "confirm_modify_order": "swap_confirm",
    "query_order_status": "swap_query_order",
}


def _has_usable_quote(state: AgentState) -> bool:
    """互换-引用消息判空：quote_content 非空且非字面量 "null"（大小写不敏感）。"""
    quote = state.get("quote_content")
    if not quote:
        return False
    return str(quote).strip().lower() != "null"


def _route_swap_entry(state: AgentState) -> str:
    """子图入口分流(DSL v2):swap_input_mode 决定文本/图片/Excel 三链。

    intent_route 写入 swap_input_mode:text | image | excel。
    图片/Excel 链跳过意图识别,直接走多模态提取 → 提交(与 DSL 拓扑一致)。
    """
    mode = state.get("swap_input_mode") or "text"
    if mode == "image":
        return "swap_image_order"
    if mode == "excel":
        return "swap_excel_order"
    return "swap_intent"


def _route_after_multimodal(state: AgentState) -> str:
    """图片/Excel 提取后路由:cascade 防御,直进提交节点。"""
    return "swap_unknown" if has_error(state) else "swap_place_order_submit"


def _route_after_swap_intent(state: AgentState) -> str:
    """swap.intent 后路由：cascade 防御 + intent 分发。"""
    if has_error(state):
        return "swap_unknown"
    intent = state.get("intent") or "unknown_intent"
    return _INTENT_TO_NODE.get(intent, "swap_unknown")


def _route_after_place_order(state: AgentState) -> str | list[str]:
    """swap.place_order 后路由：互换-引用消息判空 if-else。

    quote_content 非空且非 "null" → 选对手 ‖ 选标的 **并行**分支（两个 LLM 调用同一
    superstep，ADR 0024 重构 3），汇合到 swap_apply_picks；否则先识别并校验全新下单
    交易对手，再提交。
    """
    if has_error(state) or state.get("reply_text"):
        return "swap_unknown"
    if _has_usable_quote(state):
        return ["swap_select_counterparty", "swap_select_ticker"]
    return "swap_recognize_fresh_counterparty"


def _route_after_fresh_counterparty(state: AgentState) -> str:
    """识别请求或结构化解析失败时停止提交，沿用错误兜底。"""
    return "swap_unknown" if has_error(state) else "swap_place_order_submit"


def _route_after_apply_picks(state: AgentState) -> str:
    """swap.apply_picks 汇合后路由：任一并行分支或汇合节点出错 → 兜底，否则提交。"""
    return "swap_unknown" if has_error(state) else "swap_place_order_submit"


def build_swap_graph() -> CompiledStateGraph[AgentState, None, AgentState, SubgraphOutput]:
    """构建 swap 子图（主路由 6/6 意图全覆盖 + place_order 选择链）。"""
    g: StateGraph[AgentState, None, AgentState, SubgraphOutput] = StateGraph(AgentState, output_schema=SubgraphOutput)
    add_io_node(g, "swap_intent", swap_intent)
    g.add_node("swap_place_order", build_place_graph())
    add_io_node(g, "swap_recognize_fresh_counterparty", swap_recognize_fresh_counterparty)
    add_io_node(g, "swap_select_counterparty", swap_select_counterparty)
    add_io_node(g, "swap_select_ticker", swap_select_ticker)
    g.add_node("swap_apply_picks", swap_apply_picks)
    g.add_node("swap_place_order_submit", swap_place_order_submit)
    g.add_node("swap_confirm", swap_confirm)
    g.add_node("swap_cancel", swap_cancel)
    add_io_node(g, "swap_query_order", swap_query_order)
    g.add_node("swap_unknown", swap_unknown)
    add_io_node(g, "swap_image_order", swap_image_order)
    add_io_node(g, "swap_excel_order", swap_excel_order)

    g.add_conditional_edges(
        START,
        _route_swap_entry,
        {
            "swap_intent": "swap_intent",
            "swap_image_order": "swap_image_order",
            "swap_excel_order": "swap_excel_order",
        },
    )
    for mm_node in ("swap_image_order", "swap_excel_order"):
        g.add_conditional_edges(
            mm_node,
            _route_after_multimodal,
            {
                "swap_place_order_submit": "swap_place_order_submit",
                "swap_unknown": "swap_unknown",
            },
        )
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
    g.add_conditional_edges(
        "swap_place_order",
        _route_after_place_order,
        {
            "swap_select_counterparty": "swap_select_counterparty",
            "swap_select_ticker": "swap_select_ticker",
            "swap_recognize_fresh_counterparty": "swap_recognize_fresh_counterparty",
            "swap_unknown": "swap_unknown",
        },
    )
    g.add_conditional_edges(
        "swap_recognize_fresh_counterparty",
        _route_after_fresh_counterparty,
        {
            "swap_place_order_submit": "swap_place_order_submit",
            "swap_unknown": "swap_unknown",
        },
    )
    # 并行分支汇合：两条边都进 swap_apply_picks，LangGraph 在同一 superstep 完成后再执行汇合节点
    g.add_edge("swap_select_counterparty", "swap_apply_picks")
    g.add_edge("swap_select_ticker", "swap_apply_picks")
    g.add_conditional_edges(
        "swap_apply_picks",
        _route_after_apply_picks,
        {
            "swap_place_order_submit": "swap_place_order_submit",
            "swap_unknown": "swap_unknown",
        },
    )
    for n in (
        "swap_place_order_submit",
        "swap_confirm",
        "swap_cancel",
        "swap_query_order",
        "swap_unknown",
    ):
        g.add_edge(n, END)
    return g.compile()


__all__ = ["build_swap_graph"]
