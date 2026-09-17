"""ticker 真子图（ADR 0024 D3）：管线不再是 asyncio.gather 手写，而是 LangGraph 图。

- 3 路批量 LLM 是图上的并行分支，汇合到 merge 节点
- 逐 orgStr 的 GOATS + rank 由 Send fan-out 并行执行，结果按输入顺序确定性汇总
- 子图不继承父图 checkpointer（纯计算管线，无持久化语义）
- 对外 façade resolve_ticker_full 契约不变
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph.state import CompiledStateGraph

from app.subgraphs.ticker import resolver as resolver_mod
from app.subgraphs.ticker.graph import build_ticker_graph
from app.subgraphs.ticker.resolver import resolve_ticker_full


class _Inst:
    def __init__(self, wind_code: str, sht: str = "") -> None:
        self.wind_code = wind_code
        self.ins_sht_desc = sht
        self.ins_lng_desc = ""
        self.relevance_score = 0
        self.transaction_type_lists: list[str] = []


def test_ticker_graph_topology() -> None:
    graph = build_ticker_graph()
    assert isinstance(graph, CompiledStateGraph)
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert {
        "extract_candidates",
        "infer_codes",
        "split_keywords",
        "judge_type",
        "merge_candidates",
        "resolve_org_item",
        "assemble",
    } <= nodes
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    # 三路 LLM 是从 extract_candidates 出发的并行分支，汇合到 merge_candidates
    for llm_node in ("infer_codes", "split_keywords", "judge_type"):
        assert ("extract_candidates", llm_node) in edges
        assert (llm_node, "merge_candidates") in edges


def test_ticker_graph_does_not_inherit_parent_checkpointer() -> None:
    graph = build_ticker_graph()
    assert graph.checkpointer is False


@pytest.mark.asyncio
async def test_org_items_resolve_concurrently_and_keep_input_order(monkeypatch) -> None:
    """两个 orgStr 的 GOATS 查询必须并行（Send fan-out），汇总顺序仍按输入顺序。"""
    monkeypatch.setattr(resolver_mod, "infer_code_batch", AsyncMock(return_value={
        "茅台": ["600519.SH"], "宁德": ["300750.SZ"],
    }))
    monkeypatch.setattr(resolver_mod, "split_ticker_keywords", AsyncMock(return_value={}))
    monkeypatch.setattr(resolver_mod, "judge_ticker_type", AsyncMock(return_value={}))

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def _search(req):  # noqa: ANN001
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        kw = req.keyword_items[0].keyword
        return [_Inst("600519.SH", "贵州茅台")] if "茅台" in kw or "600519" in kw else [
            _Inst("300750.SZ", "宁德时代")
        ]

    client = MagicMock()
    client.search_securities_instrument = AsyncMock(side_effect=_search)
    monkeypatch.setattr(resolver_mod, "_make_client", lambda: client)

    resolution = await resolve_ticker_full("买入茅台和宁德各100万")
    codes = [t.wind_code for t in resolution.resolved]
    assert codes == ["600519.SH", "300750.SZ"], codes
    assert all(t.from_goats for t in resolution.resolved)
    assert peak >= 2, f"GOATS 查询未并行（峰值并发 {peak}）"
