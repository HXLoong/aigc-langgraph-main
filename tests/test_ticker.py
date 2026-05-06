"""标的识别子图测试。

每个测试用 INPUT / OUTPUT 注释标明出入参，不读代码也能知道测什么。
运行 `pytest -s tests/test_ticker.py -v` 查看详情。

Mock 要点：
- get_qwen_standard 是函数内延迟导入 → patch 在 app.llm.clients
- search_securities_instrument 是模块级导入 → patch 在 app.subgraphs.ticker
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("langgraph.graph")
pytest.importorskip("langgraph.checkpoint.memory")

from app.state import AgentState, TickerCandidate, make_initial_state
from app.subgraphs.ticker_models import TokenizeOutput


# ============================================================
# 输出辅助
# ============================================================
def _show(name: str, inputs: dict, outputs: dict):
    """打印 INPUT/OUTPUT 对比，pytest -s 时可见。
    用单个 print 避免 pytest 异步模式下 stdout 交叉。"""
    lines = [f"\n{'='*60}", f"  {name}", f"{'='*60}", "  INPUT:"]
    for k, v in inputs.items():
        lines.append(f"    {k} = {_fmt(v)}")
    lines.append("  OUTPUT:")
    for k, v in outputs.items():
        lines.append(f"    {k} = {_fmt(v)}")
    lines.append(f"{'='*60}")
    print("\n".join(lines))



def _fmt(v, max_len=200):
    """截断过长的值，便于阅读。"""
    s = repr(v)
    return s[:max_len] + "..." if len(s) > max_len else s


# ============================================================
# 快捷构造
# ============================================================
def _make_state(raw_content: str, **overrides) -> AgentState:
    s = make_initial_state({
        "conversation_id": "c1", "message_id": "m1",
        "room_id": "r", "user_id": "u", "guid": "",
        "raw_content": raw_content,
    })
    s.update(overrides)
    return s


def _mock_llm_tokenize(*, keywords=None, needs_refinement=False):
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=TokenizeOutput(
        keywords=keywords or [], needs_refinement=needs_refinement,
    ))
    return llm


def _mock_llm_rank(content: str):
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    llm.ainvoke.return_value.content = content
    return llm


def _api_candidates(*wind_codes: str):
    return [
        {"keyword": c, "windCode": c, "insShtDesc": c,
         "insLngDesc": c, "insFamily": "EQUITY", "currency": "CNY",
         "exchange": c.split(".")[-1] if "." in c else "SH", "from_goats": True}
        for c in wind_codes
    ]


# ============================================================
# 一、路由函数（纯函数，不 Mock）
# ============================================================
class TestRouteFunctions:

    def test_cache_hit_skips_to_end(self):
        """缓存命中 → 跳过整个子图
        INPUT:  state.resolved_tickers = [TickerCandidate(...)]
        OUTPUT: 返回 "__end__"
        """
        from app.subgraphs.ticker import _route_cache_check
        input_val = [TickerCandidate(keyword="x")]
        state: AgentState = {"resolved_tickers": input_val}
        result = _route_cache_check(state)
        _show("缓存命中 → __end__",
              {"resolved_tickers": input_val},
              {"route": result})
        assert result == "__end__"

    def test_cache_miss_goes_to_tokenize(self):
        """缓存未命中 → 进入分词
        INPUT:  state.resolved_tickers = []（默认空）
        OUTPUT: 返回 "tokenize_keywords"
        """
        from app.subgraphs.ticker import _route_cache_check
        state = _make_state("茅台")
        result = _route_cache_check(state)
        _show("缓存未命中 → tokenize_keywords",
              {"resolved_tickers": state.get("resolved_tickers", [])},
              {"route": result})
        assert result == "tokenize_keywords"

    def test_after_tokenize_needs_refinement(self):
        """分词质量不足 → 重试
        INPUT:  state._needs_refinement = True
        OUTPUT: 返回 "retokenize"
        """
        from app.subgraphs.ticker import _route_after_tokenize
        input_val = {"_needs_refinement": True}
        result = _route_after_tokenize(input_val)
        _show("分词不足 → retokenize", input_val, {"route": result})
        assert result == "retokenize"

    def test_after_tokenize_ok(self):
        """分词质量OK → 搜索
        INPUT:  state._needs_refinement = False（或缺失）
        OUTPUT: 返回 "search_candidates"
        """
        from app.subgraphs.ticker import _route_after_tokenize
        input_val = {}
        result = _route_after_tokenize(input_val)
        _show("分词OK → search_candidates", input_val, {"route": result})
        assert result == "search_candidates"

    def test_after_search_more_than_6(self):
        """候选 > 6 → 排序
        INPUT:  state.ticker_candidates 有 7 个
        OUTPUT: 返回 "rank_candidates"
        """
        from app.subgraphs.ticker import _route_after_search
        candidates = [TickerCandidate(keyword=str(i)) for i in range(7)]
        result = _route_after_search({"ticker_candidates": candidates})
        _show("候选>6 → rank_candidates",
              {"ticker_candidates": f"{len(candidates)}个"},
              {"route": result})
        assert result == "rank_candidates"

    def test_after_search_6_or_less(self):
        """候选 ≤ 6 → 确认
        INPUT:  state.ticker_candidates 有 3 个
        OUTPUT: 返回 "finalize_tickers"
        """
        from app.subgraphs.ticker import _route_after_search
        candidates = [TickerCandidate(keyword=str(i)) for i in range(3)]
        result = _route_after_search({"ticker_candidates": candidates})
        _show("候选≤6 → finalize_tickers",
              {"ticker_candidates": f"{len(candidates)}个"},
              {"route": result})
        assert result == "finalize_tickers"


# ============================================================
# 二、节点函数（逐个 Mock）
# ============================================================
class TestTokenizeKeywords:

    @pytest.mark.asyncio
    async def test_normal_extraction(self):
        """正常分词
        INPUT:  state.wechat_input.raw_content = "600519 000858"
        OUTPUT: raw_tickers = ["600519", "000858"], _needs_refinement = False
        """
        from app.subgraphs.ticker import tokenize_keywords

        state = _make_state("600519 000858")
        mock_llm = _mock_llm_tokenize(keywords=["600519", "000858"])
        with patch("app.llm.clients.get_qwen_standard") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await tokenize_keywords(state)

        _show("tokenize_keywords 正常分词",
              {"raw_content": state["wechat_input"]["raw_content"]},
              {"raw_tickers": result["raw_tickers"],
               "_needs_refinement": result["_needs_refinement"]})
        assert result["raw_tickers"] == ["600519", "000858"]
        assert result["_needs_refinement"] is False

    @pytest.mark.asyncio
    async def test_needs_refinement(self):
        """LLM 判断分词质量不足
        INPUT:  state.wechat_input.raw_content = "abc"
        OUTPUT: _needs_refinement = True
        """
        from app.subgraphs.ticker import tokenize_keywords

        state = _make_state("abc")
        mock_llm = _mock_llm_tokenize(keywords=["abc"], needs_refinement=True)
        with patch("app.llm.clients.get_qwen_standard") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await tokenize_keywords(state)

        _show("tokenize_keywords 质量不足",
              {"raw_content": state["wechat_input"]["raw_content"]},
              {"raw_tickers": result["raw_tickers"],
               "_needs_refinement": result["_needs_refinement"]})
        assert result["_needs_refinement"] is True

    @pytest.mark.asyncio
    async def test_llm_error_caught_by_safe_node(self):
        """LLM 抛异常 → @safe_node 兜底
        INPUT:  LLM 抛出 RuntimeError("超时")
        OUTPUT: state.error 非空，trace 中有一条 status="error"
        """
        from app.subgraphs.ticker import tokenize_keywords

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("超时"))
        with patch("app.llm.clients.get_qwen_standard") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await tokenize_keywords(_make_state("x"))

        _show("tokenize_keywords LLM异常降级",
              {"raw_content": "x", "error": "LLM抛RuntimeError"},
              {"error": result.get("error", ""),
               "trace_status": [t.get("status") for t in result.get("trace", [])]})
        assert "error" in result
        assert any(t.get("status") == "error" for t in result["trace"])


class TestRetokenize:

    @pytest.mark.asyncio
    async def test_retokenize_produces_keywords(self):
        """重试分词
        INPUT:  state.wechat_input.raw_content = "600519"
        OUTPUT: raw_tickers = ["600519.SH"], _needs_refinement = False（不回退）
        """
        from app.subgraphs.ticker import retokenize

        state = _make_state("600519")
        mock_llm = _mock_llm_tokenize(keywords=["600519.SH"])
        with patch("app.llm.clients.get_qwen_standard") as m:
            m.return_value.with_structured_output.return_value = mock_llm
            result = await retokenize(state)

        _show("retokenize 重试分词",
              {"raw_content": state["wechat_input"]["raw_content"]},
              {"raw_tickers": result["raw_tickers"],
               "_needs_refinement": result["_needs_refinement"]})
        assert result["raw_tickers"] == ["600519.SH"]
        assert result["_needs_refinement"] is False


class TestSearchCandidates:

    @pytest.mark.asyncio
    async def test_returns_candidates(self):
        """批量搜索返回候选
        INPUT:  state.raw_tickers = ["茅台", "五粮液"]
        OUTPUT: ticker_candidates 有 2 个，均 from_goats=True
        """
        from app.subgraphs.ticker import search_candidates

        api_data = _api_candidates("600519.SH", "000858.SZ")
        with patch("app.subgraphs.ticker.search_securities_instrument") as m:
            m.ainvoke = AsyncMock(return_value=api_data)
            result = await search_candidates({"raw_tickers": ["茅台", "五粮液"]})

        _show("search_candidates 正常搜索",
              {"raw_tickers": ["茅台", "五粮液"]},
              {"ticker_candidates": [(c.wind_code, c.from_goats)
                                     for c in result["ticker_candidates"]]})
        assert len(result["ticker_candidates"]) == 2
        assert result["ticker_candidates"][0].wind_code == "600519.SH"
        assert result["ticker_candidates"][1].from_goats is True

    @pytest.mark.asyncio
    async def test_empty_keywords_skips_search(self):
        """无关键词 → 跳过搜索
        INPUT:  state.raw_tickers = []
        OUTPUT: resolved_tickers = [], ticker_candidates = []
        """
        from app.subgraphs.ticker import search_candidates
        result = await search_candidates({"raw_tickers": []})
        _show("search_candidates 空关键词跳过",
              {"raw_tickers": []},
              {"resolved_tickers": result["resolved_tickers"],
               "ticker_candidates": result["ticker_candidates"]})
        assert result["resolved_tickers"] == []
        assert result["ticker_candidates"] == []

    @pytest.mark.asyncio
    async def test_api_error_returns_empty(self):
        """API 返回 _error 标记 → 降级为空
        INPUT:  API 返回 [{"_error": "连接超时"}]
        OUTPUT: resolved_tickers = [], ticker_candidates = []
        """
        from app.subgraphs.ticker import search_candidates

        with patch("app.subgraphs.ticker.search_securities_instrument") as m:
            m.ainvoke = AsyncMock(return_value=[{"_error": "连接超时"}])
            result = await search_candidates({"raw_tickers": ["600519"]})

        _show("search_candidates API错误降级",
              {"raw_tickers": ["600519"], "api_return": [{"_error": "连接超时"}]},
              {"resolved_tickers": result["resolved_tickers"],
               "ticker_candidates": result["ticker_candidates"]})
        assert result["resolved_tickers"] == []
        assert result["ticker_candidates"] == []


class TestRankCandidates:

    @pytest.mark.asyncio
    async def test_skip_when_few_candidates(self):
        """候选 ≤ 6 → 直接透传，不调 LLM
        INPUT:  ticker_candidates 有 3 个
        OUTPUT: resolved_tickers == ticker_candidates（原样返回）
        """
        from app.subgraphs.ticker import rank_candidates

        candidates = [TickerCandidate(keyword=str(i), wind_code=f"00000{i}.SZ")
                      for i in range(3)]
        result = await rank_candidates({"ticker_candidates": candidates})
        _show("rank_candidates 少量透传",
              {"ticker_candidates": [c.wind_code for c in candidates]},
              {"resolved_tickers": [c.wind_code for c in result["resolved_tickers"]]})
        assert result["resolved_tickers"] == candidates

    @pytest.mark.asyncio
    async def test_rank_to_top5(self):
        """候选 > 6 → LLM 排序筛选
        INPUT:  ticker_candidates 有 10 个
               LLM 返回 <result>["000001.SZ","000003.SZ","000005.SZ"]</result>
        OUTPUT: resolved_tickers 只有 3 个，按 LLM 排序顺序排列
        """
        from app.subgraphs.ticker import rank_candidates

        candidates = [TickerCandidate(keyword=str(i), wind_code=f"00000{i}.SZ")
                      for i in range(10)]

        mock_llm = _mock_llm_rank(
            '<analysis>x</analysis>\n<result>["000001.SZ","000003.SZ","000005.SZ"]</result>'
        )
        with patch("app.llm.clients.get_qwen_standard") as m:
            m.return_value = mock_llm
            result = await rank_candidates({
                "ticker_candidates": candidates,
                "raw_tickers": [str(i) for i in range(10)],
            })

        _show("rank_candidates LLM排序",
              {"ticker_candidates": f"{len(candidates)}个",
               "llm_response": '["000001.SZ","000003.SZ","000005.SZ"]'},
              {"resolved_tickers": [c.wind_code for c in result["resolved_tickers"]]})
        assert len(result["resolved_tickers"]) == 3
        assert result["resolved_tickers"][0].wind_code == "000001.SZ"

    @pytest.mark.asyncio
    async def test_llm_error_fallback_to_top6(self):
        """LLM 异常 → 降级返回前 6 个候选
        INPUT:  ticker_candidates 有 10 个，LLM 抛 RuntimeError
        OUTPUT: resolved_tickers 有 6 个（取前 6）
        """
        from app.subgraphs.ticker import rank_candidates

        candidates = [TickerCandidate(keyword=str(i), wind_code=f"00000{i}.SZ")
                      for i in range(10)]

        with patch("app.llm.clients.get_qwen_standard") as m:
            m.return_value.ainvoke = AsyncMock(side_effect=RuntimeError("超时"))
            result = await rank_candidates({
                "ticker_candidates": candidates,
                "raw_tickers": [str(i) for i in range(10)],
            })

        _show("rank_candidates 异常降级",
              {"ticker_candidates": f"{len(candidates)}个",
               "llm_error": "RuntimeError('超时')"},
              {"resolved_tickers": [c.wind_code for c in result["resolved_tickers"]],
               "count": len(result["resolved_tickers"])})
        assert len(result["resolved_tickers"]) == 6


class TestFinalizeTickers:

    @pytest.mark.asyncio
    async def test_direct_confirm(self):
        """候选直接确认为结果
        INPUT:  ticker_candidates = [TickerCandidate("600519", wind_code="600519.SH")]
        OUTPUT: resolved_tickers == ticker_candidates
        """
        from app.subgraphs.ticker import finalize_tickers
        candidates = [TickerCandidate(keyword="600519", wind_code="600519.SH")]
        result = await finalize_tickers({"ticker_candidates": candidates})
        _show("finalize_tickers 直接确认",
              {"ticker_candidates": [(c.keyword, c.wind_code) for c in candidates]},
              {"resolved_tickers": [(c.keyword, c.wind_code)
                                    for c in result["resolved_tickers"]]})
        assert result["resolved_tickers"] == candidates


# ============================================================
# 三、子图整体（5 条拓扑路径）
# ============================================================
class TestTickerGraph:

    @pytest.mark.asyncio
    async def test_path1_cache_hit(self):
        """路径1：缓存命中，直接返回
        INPUT:  state 已有 resolved_tickers = [600519.SH]
        OUTPUT: resolved_tickers 不变，不经任何节点
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.ticker import build_ticker_graph

        graph = build_ticker_graph().compile(checkpointer=InMemorySaver())
        state = _make_state("茅台", resolved_tickers=[
            TickerCandidate(keyword="600519", wind_code="600519.SH", from_goats=True),
        ])
        result = await graph.ainvoke(
            state, {"configurable": {"thread_id": "c-cache"}},
        )

        _show("子图路径1: 缓存命中",
              {"raw_content": state["wechat_input"]["raw_content"],
               "resolved_tickers_in": [(c.keyword, c.wind_code)
                                       for c in state["resolved_tickers"]]},
              {"resolved_tickers_out": [(c.keyword, c.wind_code)
                                        for c in result["resolved_tickers"]],
               "trace_nodes": list(dict.fromkeys(t["node"] for t in result["trace"]))})
        assert len(result["resolved_tickers"]) == 1
        assert result["resolved_tickers"][0].wind_code == "600519.SH"

    @pytest.mark.asyncio
    async def test_path2_tokenize_search_finalize(self):
        """路径2：分词 → 搜索(≤6) → 确认
        INPUT:  raw_content = "查600519和000858"
               LLM 返回 keywords=["600519", "000858"]
               API 返回 2 个候选
        OUTPUT: resolved_tickers 有 2 个
                trace 包含 tokenize_keywords / search_candidates / finalize_tickers
                trace 不含 retokenize / rank_candidates
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.ticker import build_ticker_graph

        mock_tok = _mock_llm_tokenize(keywords=["600519", "000858"])
        api_data = _api_candidates("600519.SH", "000858.SZ")

        with patch("app.llm.clients.get_qwen_standard") as m_std, \
             patch("app.subgraphs.ticker.search_securities_instrument") as m_api:
            m_std.return_value.with_structured_output.return_value = mock_tok
            m_api.ainvoke = AsyncMock(return_value=api_data)

            graph = build_ticker_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(
                _make_state("查600519和000858"),
                {"configurable": {"thread_id": "c-simple"}},
            )

        _show("子图路径2: 分词→搜索→确认",
              {"raw_content": "查600519和000858"},
              {"resolved_tickers": [(c.keyword, c.wind_code)
                                    for c in result["resolved_tickers"]],
               "trace_nodes": list(dict.fromkeys(t["node"] for t in result["trace"]))})
        assert len(result["resolved_tickers"]) == 2
        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        assert "tokenize_keywords" in trace_nodes
        assert "search_candidates" in trace_nodes
        assert "finalize_tickers" in trace_nodes
        assert "retokenize" not in trace_nodes
        assert "rank_candidates" not in trace_nodes

    @pytest.mark.asyncio
    async def test_path3_tokenize_retokenize(self):
        """路径3：分词 → 重试 → 搜索 → 确认
        INPUT:  raw_content = "mt"
               第1次 LLM: keywords=["mt"], needs_refinement=True
               第2次 LLM: keywords=["600519.SH"], needs_refinement=False
               API 返回 1 个候选
        OUTPUT: resolved_tickers = [600519.SH]
                trace 包含 tokenize_keywords / retokenize / search_candidates / finalize_tickers
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.ticker import build_ticker_graph

        call_count = [0]

        def make_output(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                return TokenizeOutput(keywords=["mt"], needs_refinement=True)
            return TokenizeOutput(keywords=["600519.SH"], needs_refinement=False)

        mock_tok = MagicMock()
        mock_tok.ainvoke = AsyncMock(side_effect=make_output)
        api_data = _api_candidates("600519.SH")

        with patch("app.llm.clients.get_qwen_standard") as m_std, \
             patch("app.subgraphs.ticker.search_securities_instrument") as m_api:
            m_std.return_value.with_structured_output.return_value = mock_tok
            m_api.ainvoke = AsyncMock(return_value=api_data)

            graph = build_ticker_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(
                _make_state("mt"),
                {"configurable": {"thread_id": "c-retry"}},
            )

        _show("子图路径3: 分词→重试→搜索→确认",
              {"raw_content": "mt"},
              {"resolved_tickers": [(c.keyword, c.wind_code)
                                    for c in result["resolved_tickers"]],
               "trace_nodes": list(dict.fromkeys(t["node"] for t in result["trace"])),
               "llm_call_count": call_count[0]})
        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        assert "tokenize_keywords" in trace_nodes
        assert "retokenize" in trace_nodes
        assert len(result["resolved_tickers"]) == 1
        assert result["resolved_tickers"][0].wind_code == "600519.SH"

    @pytest.mark.asyncio
    async def test_path4_search_rank(self):
        """路径4：分词 → 搜索(>6) → 排序
        INPUT:  raw_content = "0 1 2 3 4 5 6 7 8 9"
               LLM 分词返回 10 个 keywords
               API 返回 10 个候选
               rank LLM 返回排序后前 3 个
        OUTPUT: resolved_tickers 有 3 个
                trace 不含 finalize_tickers（rank 后直接 END）
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.ticker import build_ticker_graph

        mock_tok = _mock_llm_tokenize(keywords=[str(i) for i in range(10)])
        api_data = _api_candidates(*[f"00000{i}.SZ" for i in range(10)])
        mock_rank = _mock_llm_rank(
            '<analysis>x</analysis>\n<result>["000001.SZ","000003.SZ","000005.SZ"]</result>'
        )

        with patch("app.llm.clients.get_qwen_standard") as m_std, \
             patch("app.subgraphs.ticker.search_securities_instrument") as m_api:
            m_std.return_value.with_structured_output.return_value = mock_tok
            m_std.return_value.ainvoke = mock_rank.ainvoke
            m_api.ainvoke = AsyncMock(return_value=api_data)

            graph = build_ticker_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(
                _make_state(" ".join(str(i) for i in range(10))),
                {"configurable": {"thread_id": "c-rank"}},
            )

        _show("子图路径4: 分词→搜索→排序",
              {"raw_content": "0 1 2 ... 9 (10个)", "candidates": "10个"},
              {"resolved_tickers": [(c.keyword, c.wind_code)
                                    for c in result["resolved_tickers"]],
               "trace_nodes": list(dict.fromkeys(t["node"] for t in result["trace"]))})
        trace_nodes = list(dict.fromkeys(t["node"] for t in result["trace"]))
        assert "rank_candidates" in trace_nodes
        assert "finalize_tickers" not in trace_nodes
        assert len(result["resolved_tickers"]) == 3

    @pytest.mark.asyncio
    async def test_path5_empty_input(self):
        """路径5：空消息 → 分词无结果 → 确认空列表
        INPUT:  raw_content = ""
               LLM 返回 keywords=[]
        OUTPUT: resolved_tickers = []
        """
        from langgraph.checkpoint.memory import InMemorySaver
        from app.subgraphs.ticker import build_ticker_graph

        mock_tok = _mock_llm_tokenize(keywords=[])
        with patch("app.llm.clients.get_qwen_standard") as m_std:
            m_std.return_value.with_structured_output.return_value = mock_tok
            graph = build_ticker_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(
                _make_state(""),
                {"configurable": {"thread_id": "c-empty"}},
            )

        _show("子图路径5: 空消息",
              {"raw_content": ""},
              {"resolved_tickers": result["resolved_tickers"],
               "trace_nodes": list(dict.fromkeys(t["node"] for t in result["trace"]))})
        assert result["resolved_tickers"] == []

    def test_graph_has_5_nodes(self):
        """图结构完整性
        OUTPUT: 5 个节点全部注册
        """
        from app.subgraphs.ticker import build_ticker_graph
        g = build_ticker_graph()
        nodes = {"tokenize_keywords", "retokenize", "search_candidates",
                 "rank_candidates", "finalize_tickers"}
        _show("图结构: 5个节点",
              {"expected": sorted(nodes)},
              {"actual": sorted(g.nodes)})
        assert nodes.issubset(g.nodes)


# ============================================================
# 四、实际使用的工具：search_securities_instrument
# ============================================================
class TestSearchSecuritiesInstrument:

    @pytest.mark.asyncio
    async def test_batch_search(self):
        """批量搜索正常返回
        INPUT:  keyword_items = [{"isFull":False,"keyword":"贵州茅台"},
                                  {"isFull":False,"keyword":"五粮液"}]
               HTTP 返回 code=0, data=[...]
        OUTPUT: [{windCode:"600519.SH", from_goats:True}, ...]  共 2 条
        """
        from app.subgraphs.ticker_tools import search_securities_instrument

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "data": [
                {"windCode": "600519.SH", "insShtDesc": "贵州茅台"},
                {"windCode": "000858.SZ", "insShtDesc": "五粮液"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.request", AsyncMock(return_value=mock_response)):
            result = await search_securities_instrument.ainvoke({
                "keyword_items": [
                    {"isFull": False, "keyword": "贵州茅台"},
                    {"isFull": False, "keyword": "五粮液"},
                ],
            })

        _show("search_securities_instrument 批量搜索",
              {"keyword_items": ["贵州茅台", "五粮液"]},
              {"result": [(r["windCode"], r["insShtDesc"], r["from_goats"])
                          for r in result]})
        assert len(result) == 2
        assert result[0]["windCode"] == "600519.SH"
        assert result[0]["from_goats"] is True

    @pytest.mark.asyncio
    async def test_empty_keywords(self):
        """空关键词直接返回 []
        INPUT:  keyword_items = []
        OUTPUT: []
        """
        from app.subgraphs.ticker_tools import search_securities_instrument
        result = await search_securities_instrument.ainvoke({"keyword_items": []})
        _show("search_securities_instrument 空关键词",
              {"keyword_items": []},
              {"result": result})
        assert result == []

    @pytest.mark.asyncio
    async def test_business_error(self):
        """业务 code != 0 → 返回 []
        INPUT:  keyword_items = [{"keyword":"x"}]
               HTTP 返回 code=500
        OUTPUT: []
        """
        from app.subgraphs.ticker_tools import search_securities_instrument

        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 500, "msg": "内部错误"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.request", AsyncMock(return_value=mock_response)):
            result = await search_securities_instrument.ainvoke({
                "keyword_items": [{"isFull": False, "keyword": "x"}],
            })
        _show("search_securities_instrument 业务错误",
              {"keyword_items": [{"keyword": "x"}], "api_code": 500},
              {"result": result})
        assert result == []

    @pytest.mark.asyncio
    async def test_connect_timeout(self):
        """连接超时 → 返回 _error 标记
        INPUT:  httpx.AsyncClient.request 抛 ConnectTimeout
        OUTPUT: [{"_error": "..."}]
        """
        from app.subgraphs.ticker_tools import search_securities_instrument

        with patch("httpx.AsyncClient.request",
                   AsyncMock(side_effect=__import__("httpx").ConnectTimeout("超时"))):
            result = await search_securities_instrument.ainvoke({
                "keyword_items": [{"isFull": False, "keyword": "x"}],
            })

        _show("search_securities_instrument 连接超时",
              {"keyword_items": [{"keyword": "x"}], "error": "ConnectTimeout"},
              {"result": result})
        assert len(result) == 1
        assert result[0].get("_error")


# ============================================================
# 五、ticker_tools.py 中未使用的工具（仅记录）
# ============================================================
#
# ✅ search_securities_instrument — 已用（见第四部分）
#
# ❌ tokenize_tickers       — 未用：子图改用 LLM tokenize_keywords 节点
# ❌ regex_validate         — 未用：正则校验未接入当前拓扑
# ❌ web_search_bocha       — 未用：搜索引擎补全未接入
# ❌ web_search_tavily      — 未用：同上
# ❌ llm_rank_candidates    — 未用：子图有自己的 rank_candidates 节点
# ❌ assert_from_goats      — 未用：_dict_to_ticker_candidate 已强制 from_goats
