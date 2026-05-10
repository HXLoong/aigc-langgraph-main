"""主图组装 + 一级路由（ADR 0001 D6 + ADR 0015）。

M1 阶段：子图（swap/option/option_close）为占位 stub；intent_route 占位。
M2 阶段：intent_route 已实现真三层路由（ADR 0015）；子图逐一替换为真实编译入口。
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.nodes.fallback import fallback
from app.nodes.ingest import ingest
from app.nodes.intent_route import intent_route
from app.nodes.persist import persist
from app.nodes.render import render
from app.subgraphs.swap import build_swap_graph


# ============================================================
# 占位子图 stub（M2 子图 PR 逐个替换）
# ============================================================


@safe_node
async def _option_stub(state: AgentState) -> dict[str, Any]:
    """占位 option 子图。M2 替换为 build_option_graph().compile()。"""
    return {"intent": state.get("intent") or "new_inquiry"}


@safe_node
async def _option_close_stub(state: AgentState) -> dict[str, Any]:
    """占位 option_close 子图。M2 替换为 build_close_graph().compile()。"""
    return {"intent": state.get("intent") or "close_order_request"}


# ============================================================
# 路由函数（含 cascade 防御 + unknown 兜底）
# ============================================================


def _route_after_intent(state: AgentState) -> str:
    """intent_route 节点后的路由。

    优先级：
    1. state['error'] 存在 → fallback（cascade 防御，CLAUDE.md 核心原则第 8 条）
    2. product_type == "unknown" → fallback（ADR 0015 第 3 层兜底）
    3. 否则按 product_type 选子图
    """
    if state.get("error") is not None:
        return "fallback"
    pt = state.get("product_type", "unknown")
    if pt == "unknown":
        return "fallback"
    return pt


# ============================================================
# 主图组装
# ============================================================


def build_main_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """组装并编译主图。

    流程：
        START → ingest → intent_route → [route_after_intent] →
            swap | option | option_close | fallback → persist → render → END

    cascade 防御：
    - intent_route 写 state['error'] → 跳 fallback
    - product_type == 'unknown' → 跳 fallback
    """
    g: StateGraph = StateGraph(AgentState)

    g.add_node("ingest", ingest)
    g.add_node("intent_route", intent_route)
    g.add_node("swap", build_swap_graph())
    g.add_node("option", _option_stub)
    g.add_node("option_close", _option_close_stub)
    g.add_node("fallback", fallback)
    g.add_node("persist", persist)
    g.add_node("render", render)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "intent_route")
    g.add_conditional_edges(
        "intent_route",
        _route_after_intent,
        {
            "swap": "swap",
            "option": "option",
            "option_close": "option_close",
            "fallback": "fallback",
        },
    )
    for sub in ("swap", "option", "option_close", "fallback"):
        g.add_edge(sub, "persist")
    g.add_edge("persist", "render")
    g.add_edge("render", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


__all__ = ["build_main_graph"]
