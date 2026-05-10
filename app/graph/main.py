"""主图组装 + 一级路由（ADR 0001 D6）。

M1 阶段：子图（swap/option/close）为占位 stub。
M2 阶段：替换为真实子图编译入口。
"""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.nodes.ingest import ingest
from app.nodes.persist import persist
from app.nodes.render import render


# ============================================================
# M1 占位子图 stub（M2 替换为真实子图）
# ============================================================


@safe_node
async def _swap_stub(state: AgentState) -> dict[str, Any]:
    """M1: swap 子图占位。M2 替换为 build_swap_graph().compile()。"""
    return {"intent": state.get("intent") or "place_order_request"}


@safe_node
async def _option_stub(state: AgentState) -> dict[str, Any]:
    """M1: option 子图占位。"""
    return {"intent": state.get("intent") or "new_inquiry"}


@safe_node
async def _close_stub(state: AgentState) -> dict[str, Any]:
    """M1: close 子图占位。"""
    return {"intent": state.get("intent") or "close_order_request"}


# ============================================================
# 一级路由
# ============================================================


def _route_by_product(state: AgentState) -> str:
    """主图路由：按 product_type 选子图。

    ingest 节点已在 M1 中默认设置 product_type = swap；M2 阶段会根据
    raw_text + history 用 LLM 分类后正确设置。
    """
    pt = state.get("product_type", "swap")
    return pt


# ============================================================
# 主图组装
# ============================================================


def build_main_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """组装并编译主图。

    流程：
        START → ingest → [route by product_type] → swap | option | close → persist → render → END

    入参：
        checkpointer: AIOMySQLSaver 等。开发/测试可传 None；
                      生产必须传以支持多轮对话（ADR 0009）。
    """
    g: StateGraph = StateGraph(AgentState)

    g.add_node("ingest", ingest)
    g.add_node("swap", _swap_stub)
    g.add_node("option", _option_stub)
    g.add_node("close", _close_stub)
    g.add_node("persist", persist)
    g.add_node("render", render)

    g.add_edge(START, "ingest")
    g.add_conditional_edges(
        "ingest",
        _route_by_product,
        {"swap": "swap", "option": "option", "close": "close"},
    )
    for sub in ("swap", "option", "close"):
        g.add_edge(sub, "persist")
    g.add_edge("persist", "render")
    g.add_edge("render", END)

    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()


__all__ = ["build_main_graph"]
