"""ticker 子图拓扑（ADR 0024 D3：把 asyncio.gather 手写的 12 步管线变成真图）。

    START → extract_candidates ─┬─ 无候选 ──────────────────────────────┐
                                └─ infer_codes ‖ split_keywords ‖ judge_type → merge_candidates
                                       → Send(resolve_org_item) × N（并行）→ assemble → END

- 私有 State（TickerState），不与 AgentState 共享；compile(checkpointer=False) 不继承
  父图 checkpointer——这是纯计算管线，没有跨轮持久化语义
- 节点函数住在 resolver.py（测试按 `resolver.<name>` monkeypatch 三个边界：批量 LLM /
  rank / GOATS client），本模块只负责拓扑
- 业务子图仍通过 `resolve_ticker_full()` façade 调用；LangChain 会把父图 config /
  callbacks 经 contextvars 传播进来，LangFuse 上能看到每个节点的 span
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.subgraphs.ticker import resolver as r


def build_ticker_graph() -> CompiledStateGraph:
    g: StateGraph = StateGraph(r.TickerState)
    g.add_node("extract_candidates", r.extract_candidates)
    g.add_node("infer_codes", r.infer_codes)
    g.add_node("split_keywords", r.split_keywords)
    g.add_node("judge_type", r.judge_type)
    g.add_node("merge_candidates", r.merge_candidates)
    g.add_node("resolve_org_item", r.resolve_org_item)
    g.add_node("assemble", r.assemble)

    g.add_edge(START, "extract_candidates")
    g.add_conditional_edges(
        "extract_candidates",
        r.route_after_extract,
        ["infer_codes", "split_keywords", "judge_type", "assemble"],
    )
    for llm_node in ("infer_codes", "split_keywords", "judge_type"):
        g.add_edge(llm_node, "merge_candidates")
    g.add_conditional_edges(
        "merge_candidates", r.fan_out_org_items, ["resolve_org_item", "assemble"]
    )
    g.add_edge("resolve_org_item", "assemble")
    g.add_edge("assemble", END)
    return g.compile(checkpointer=False, name="ticker")


@lru_cache(maxsize=1)
def get_ticker_graph() -> CompiledStateGraph:
    """进程级单例：拓扑固定，编译一次即可。"""
    return build_ticker_graph()


__all__ = ["build_ticker_graph", "get_ticker_graph"]
