"""主图组装：会话保护 → 存量优先与版本分流 → 单业务动作的产品路由。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.cascade import has_error
from app.graph.retry import add_io_node
from app.graph.state import AgentState
from app.nodes.entry_route import entry_route
from app.nodes.entry_route import select_entry_branch as _route_entry
from app.nodes.fallback import fallback
from app.nodes.fast_query import (
    existing_command_query,
    quick_inquiry,
)
from app.nodes.ingest import ingest
from app.nodes.intent_route import intent_route
from app.nodes.parse_instruction import parse_instruction
from app.nodes.persist import persist
from app.nodes.persist_intent import make_persist_intent
from app.nodes.pre_route import pre_route
from app.nodes.prepare_input import prepare_input
from app.nodes.prepare_parse_context import prepare_parse_context
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


def _route_after_ingest(state: AgentState) -> str:
    """入口准备异常或会话过期时退出，不进入三分支业务路由。"""
    if has_error(state) or state.get("session_status") == "expired":
        return "render"
    return "entry_route"


def _route_after_input(state: AgentState) -> str:
    """准备故障直接回复；明确拒绝先写消息意图，均不进入交易分支。"""
    if has_error(state):
        return "render"
    return "persist_intent" if state.get("reply_text") else "pre_route"


def _route_after_entry(state: AgentState) -> str:
    """入口错误先收尾，版本静默分支不写回消息意图。"""
    return "render" if has_error(state) else _route_entry(state)


def _route_after_intent(state: AgentState) -> str:
    """intent_route 节点后的路由。

    优先级：
    1. state['error'] 存在 → fallback（cascade 防御，CLAUDE.md 核心原则第 9 条）
    2. product_type == "unknown" → fallback（DSL v2 一级分支 false 落兜底）
    3. 否则按 product_type 选子图
    """
    if has_error(state):
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
    """会话保护后先版本分流，普通指令读取附件后只联合解析一次。

    快速询价与存量查询沿既有外部入口；普通流程先准备只读上下文，
    再执行唯一模型节点。子图错误沿 cascade 收尾，回复后记录历史与审计。
    详细拓扑见 docs/architecture/main-graph-flow.md，各子图另有独立文档。
    """
    # 1. 注册入口、解析与产品边界，只有后端只读查询挂重试策略。
    g: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)

    g.add_node("ingest", ingest)
    g.add_node("prepare_input", prepare_input)
    g.add_node("entry_route", entry_route)
    g.add_node("quick_inquiry", quick_inquiry)
    add_io_node(g, "existing_command_query", existing_command_query)
    g.add_node("pre_route", pre_route)
    g.add_node("intent_route", intent_route)
    g.add_node("parse_instruction", parse_instruction)
    add_io_node(g, "prepare_parse_context", prepare_parse_context)
    # ADR 0024 D3：子图原生嵌入。子图 output_schema=SubgraphOutput 限定写回面，
    # trace 按 id 合并（merge_by_id），父图不再需要 ainvoke + Overwrite 手工包装
    g.add_node("swap", build_swap_graph())
    g.add_node("option", build_option_graph())
    g.add_node("option_close", build_close_graph())
    g.add_node("fallback", fallback)
    g.add_node("render", render)
    g.add_node("persist_intent", RunnableLambda(make_persist_intent(message_client_factory)))
    g.add_node("persist", persist)
    g.add_node("remember_confirmed_params", remember_confirmed_params)
    g.add_node("record_history", record_history)

    # 2. 所有路由先处理错误，再进入单一业务动作。
    g.add_edge(START, "ingest")
    g.add_conditional_edges(
        "ingest",
        _route_after_ingest,
        {"entry_route": "entry_route", "render": "render"},
    )
    g.add_conditional_edges("prepare_input", _route_after_input, ["pre_route", "persist_intent", "render"])
    g.add_conditional_edges(
        "entry_route",
        _route_after_entry,
        {
            "quick_inquiry": "quick_inquiry",
            "existing_command_query": "existing_command_query",
            "pre_route": "prepare_input",
            "ignore": "render",
            "render": "render",
        },
    )
    g.add_edge("pre_route", "intent_route")
    g.add_edge("intent_route", "prepare_parse_context")
    g.add_edge("prepare_parse_context", "parse_instruction")
    g.add_conditional_edges(
        "parse_instruction",
        _route_after_intent,
        {
            "swap": "swap",
            "option": "option",
            "option_close": "option_close",
            "fallback": "fallback",
        },
    )
    for sub in ("swap", "option", "option_close", "fallback", "quick_inquiry", "existing_command_query"):
        g.add_edge(sub, "persist_intent")
    # 3. 保留消息写回、真实回复、历史和审计，整体只返回本次结果。
    g.add_edge("persist_intent", "render")
    g.add_edge("render", "remember_confirmed_params")
    g.add_edge("remember_confirmed_params", "record_history")
    g.add_edge("record_history", "persist")
    g.add_edge("persist", END)

    # LangFuse 不在图级注入（ADR 0024 D5）：统一由 app/api/routes.py 按请求把 handler 放进
    # config["callbacks"]，生产与开发同一条 trace_id / session 契约
    return g.compile(checkpointer=checkpointer) if checkpointer is not None else g.compile()


__all__ = ["build_main_graph"]
