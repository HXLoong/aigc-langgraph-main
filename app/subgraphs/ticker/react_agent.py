"""ticker 子图 - ReAct Agent。

ADR 0008 + ADR 0010 + grill-with-docs 2026-05-10 运行时约束（a/b/c）。

Day 1 范围：搭建可编译的 ReAct Agent 骨架（thinking 模型 + 4 工具 stub +
hard cap 8）。后续 PR 接真 GOATS / 真 prompt / HITL 多命中消歧。
"""
from __future__ import annotations

from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from app.llm.clients import get_qwen_thinking
from app.subgraphs.ticker.tools import TICKER_TOOLS

# ============================================================
# 运行时常量（grill-with-docs 2026-05-10 第 7 决策，ADR 0008 a）
# ============================================================

#: ReAct Agent 最大业务步数（4 基础 + 4 reflection/重试 buffer）
TICKER_MAX_STEPS = 8

#: LangGraph recursion_limit（每业务步 ≈ 2 个内部跳转：think + tool_call）
TICKER_RECURSION_LIMIT = TICKER_MAX_STEPS * 2


def build_ticker_react_agent() -> CompiledStateGraph:
    """创建 ticker 子图的 ReAct Agent。

    Day 1：thinking 模型 + 4 工具 stub + recursion_limit=16。
    超过 cap 触发 LangGraph `GraphRecursionError`，由调用方/主图 cascade
    防御接管走 fallback。
    """
    llm = get_qwen_thinking()
    agent = create_agent(llm, tools=TICKER_TOOLS)
    return agent.with_config({"recursion_limit": TICKER_RECURSION_LIMIT})


__all__ = [
    "TICKER_MAX_STEPS",
    "TICKER_RECURSION_LIMIT",
    "build_ticker_react_agent",
]
