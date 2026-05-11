"""ticker 子图编译入口。

主图通过 `g.add_node("ticker", build_ticker_graph())` 嵌入。

注意：ReAct Agent 内部使用自己的 MessagesState，与主图 AgentState 不同。
M2 后续 PR 会建立 wrapper 节点，把 `state.raw_text → message → ReAct →
state.tickers` 做转换。Day 1 仅暴露独立可调用的 ReAct Agent。
"""
from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from app.subgraphs.ticker.react_agent import build_ticker_react_agent


def build_ticker_graph() -> CompiledStateGraph:
    """构建 ticker 子图（Day 1：直接返回 ReAct Agent）。"""
    return build_ticker_react_agent()


__all__ = ["build_ticker_graph"]
