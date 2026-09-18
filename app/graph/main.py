"""主图组装 + 一级路由（ADR 0001 D6 + ADR 0015）。

M1 阶段：子图（swap/option/option_close）为占位 stub；intent_route 占位。
M2 阶段：intent_route 已实现真三层路由（ADR 0015）；子图逐一替换为真实编译入口。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.retry import add_io_node
from app.graph.state import AgentState
from app.nodes.fallback import fallback
from app.nodes.fast_query import (
    existing_command_query,
    is_existing_command,
    is_fast_query,
    quick_inquiry,
)
from app.nodes.ingest import ingest
from app.nodes.intent_route import intent_route
from app.nodes.persist import persist
from app.nodes.persist_intent import make_persist_intent
from app.nodes.pre_route import pre_route
from app.nodes.record_history import record_history
from app.nodes.remember_confirmed import remember_confirmed_params
from app.nodes.render import render
from app.subgraphs.close import build_close_graph
from app.subgraphs.option import build_option_graph
from app.subgraphs.swap import build_swap_graph
from app.tools.message_client import MessageClient

# ============================================================
# 路由函数（含 cascade 防御 + unknown 兜底）
# ============================================================


def _route_entry(state: AgentState) -> str:
    """ingest 后的前置分流（DSL v2「判断快速询价」if-else）。

    1. fast_query == "1" → 快速询价链（GOATS rfq parser → 期权快速询价）
    2. existing_command == "1" 且 at_bot == "0" → 存量兼容交易查询
    3. 其他 → pre_route（对手/候选提取）→ intent_route 一级路由
    """
    if is_fast_query(state):
        return "quick_inquiry"
    if is_existing_command(state):
        return "existing_command_query"
    return "pre_route"


def _route_after_intent(state: AgentState) -> str:
    """intent_route 节点后的路由。

    优先级：
    1. state['error'] 存在 → fallback（cascade 防御，CLAUDE.md 核心原则第 8 条）
    2. product_type == "unknown" → fallback（DSL v2 一级分支 false 落兜底）
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
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    message_client_factory: Callable[[], MessageClient] | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """组装并编译主图（DSL v2 拓扑）。

    流程：
        START → ingest（一轮边界：清 trace / per-turn 输出与业务对象，ADR 0024 D2）→ [route_entry] →
            quick_inquiry | existing_command_query          （前置分支,直达 persist）
          | pre_route → intent_route → [route_after_intent] →
                swap | option | option_close | fallback
        → persist_intent → render → remember_confirmed_params → record_history → persist → END

    cascade 防御：
    - intent_route 写 state['error'] → 跳 fallback
    - product_type == 'unknown' → 跳 fallback
    """
    g: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)

    g.add_node("ingest", ingest)
    g.add_node("quick_inquiry", quick_inquiry)
    add_io_node(g, "existing_command_query", existing_command_query)
    g.add_node("pre_route", pre_route)
    add_io_node(g, "intent_route", intent_route)
    # ADR 0024 D3：子图原生嵌入。子图 output_schema=SubgraphOutput 限定写回面，
    # trace 按 id 合并（merge_by_id），父图不再需要 ainvoke + Overwrite 手工包装
    g.add_node("swap", build_swap_graph())
    g.add_node("option", build_option_graph())
    g.add_node("option_close", build_close_graph())
    g.add_node("fallback", fallback)
    g.add_node("persist_intent", RunnableLambda(make_persist_intent(message_client_factory)))
    g.add_node("persist", persist)
    g.add_node("render", render)
    g.add_node("remember_confirmed_params", remember_confirmed_params)
    g.add_node("record_history", record_history)

    g.add_edge(START, "ingest")
    g.add_conditional_edges(
        "ingest",
        _route_entry,
        {
            "quick_inquiry": "quick_inquiry",
            "existing_command_query": "existing_command_query",
            "pre_route": "pre_route",
        },
    )
    g.add_edge("pre_route", "intent_route")
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
        g.add_edge(sub, "persist_intent")
    for sub in ("quick_inquiry", "existing_command_query"):
        g.add_edge(sub, "render")
    g.add_edge("persist_intent", "render")
    g.add_edge("render", "remember_confirmed_params")
    g.add_edge("remember_confirmed_params", "record_history")
    g.add_edge("record_history", "persist")
    g.add_edge("persist", END)

    # LangFuse 不在图级注入（ADR 0024 D5）：统一由 app/api/routes.py 按请求把 handler 放进
    # config["callbacks"]，生产与开发同一条 trace_id / session 契约
    return g.compile(checkpointer=checkpointer) if checkpointer is not None else g.compile()


__all__ = ["build_main_graph"]
