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

from app.graph.state import AgentState
from app.nodes.fallback import fallback
from app.nodes.ingest import ingest
from app.nodes.intent_route import intent_route
from app.nodes.persist import persist
from app.nodes.persist_intent import make_persist_intent
from app.nodes.record_history import record_history
from app.nodes.render import render
from app.subgraphs.close import build_close_graph
from app.subgraphs.option import build_option_graph
from app.subgraphs.swap import build_swap_graph
from app.tools.message_client import MessageClient

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


def _business_update(state: AgentState) -> dict[str, Any]:
    """子图只读历史；避免将旧历史回传给父图的 add reducer 再累加一次。"""
    return {key: value for key, value in state.items() if key != "history_messages"}


def build_main_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    message_client_factory: Callable[[], MessageClient] | None = None,
) -> CompiledStateGraph:
    """组装并编译主图。

    流程：
        START → ingest → intent_route → [route_after_intent] →
            swap | option | option_close | fallback → persist_intent → persist → render →
            record_history → END

    message_client_factory 未注入时不写外部消息表；FastAPI lifespan 显式注入。

    cascade 防御：
    - intent_route 写 state['error'] → 跳 fallback
    - product_type == 'unknown' → 跳 fallback
    """
    g: StateGraph = StateGraph(AgentState)

    g.add_node("ingest", ingest)
    g.add_node("intent_route", intent_route)
    g.add_node("swap", build_swap_graph() | RunnableLambda(_business_update))
    g.add_node("option", build_option_graph() | RunnableLambda(_business_update))
    g.add_node("option_close", build_close_graph() | RunnableLambda(_business_update))
    g.add_node("fallback", fallback)
    g.add_node("persist_intent", RunnableLambda(make_persist_intent(message_client_factory)))
    g.add_node("persist", persist)
    g.add_node("render", render)
    g.add_node("record_history", record_history)

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
        g.add_edge(sub, "persist_intent")
    g.add_edge("persist_intent", "persist")
    g.add_edge("persist", "render")
    g.add_edge("render", "record_history")
    g.add_edge("record_history", END)

    if checkpointer is not None:
        compiled = g.compile(checkpointer=checkpointer)
    else:
        compiled = g.compile()
    return _attach_langfuse_callbacks(compiled)


def _attach_langfuse_callbacks(compiled: CompiledStateGraph) -> CompiledStateGraph:
    """如果配置了 Langfuse，自动把 CallbackHandler 注入到 graph 调用，
    让云端 eval / 业务调用都能拿到 per-node trace（LLM 调用 / latency / token）。

    使用 with_config 而不是 monkey-patch ainvoke：with_config 是 LangChain 官方
    机制，会把默认 callbacks 通过 RunnableConfig.merge 合并到每次调用，调用方
    自带的 callbacks 仍然生效。
    """
    try:
        from app.config import get_settings
        settings = get_settings()
        if not (settings.enable_langfuse and settings.langfuse_public_key and settings.langfuse_secret_key):
            return compiled

        import os

        from langfuse.langchain import CallbackHandler  # type: ignore[import-not-found]

        # langfuse v4 CallbackHandler 只读 os.environ；先回填 env
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
        os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)

        handler = CallbackHandler()
        return compiled.with_config(callbacks=[handler])
    except Exception as exc:  # noqa: BLE001
        # Langfuse 未安装 / 网络异常 → 不阻断业务，返回未包装图；
        # #155 裁决：从静默升为 warning——生产 LangFuse 挂掉必须有信号
        import logging

        logging.getLogger(__name__).warning("Langfuse CallbackHandler 注入失败，trace 降级：%s", exc)
        return compiled


__all__ = ["build_main_graph"]
