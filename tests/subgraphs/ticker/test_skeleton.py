"""ticker 子图骨架测试 - Day 1 不联网，仅验证编译 + 工具签名。

后续 PR 加：
- mock LLM 集成测试（#M2-Ticker-2/3/4）
- 真 LLM E2E 测试（#M2-Ticker-5）
- recursion_limit 触发 GraphRecursionError 验证
"""
from __future__ import annotations

from app.subgraphs.ticker.react_agent import (
    TICKER_MAX_STEPS,
    TICKER_RECURSION_LIMIT,
)
from app.subgraphs.ticker.tools import (
    TICKER_TOOLS,
    completeness,
    infer_code,
    rank,
    tokenize,
)


# ============================================================
# 运行时常量（grill-with-docs 第 7 决策 / ADR 0008 a）
# ============================================================


def test_ticker_hard_cap_is_8_steps() -> None:
    """ADR 0008 a · hard cap = 8 步（不要随意改大）。"""
    assert TICKER_MAX_STEPS == 8


def test_ticker_recursion_limit_is_double_max_steps() -> None:
    """每业务步 ≈ 2 个 LangGraph 跳转，所以 recursion_limit = 2 * MAX_STEPS。"""
    assert TICKER_RECURSION_LIMIT == TICKER_MAX_STEPS * 2
    assert TICKER_RECURSION_LIMIT == 16


# ============================================================
# 工具签名验证
# ============================================================


def test_ticker_tools_count_is_4() -> None:
    """ADR 0008 + #M2-Ticker-1：4 个工具（tokenize / completeness / rank / infer_code）。"""
    assert len(TICKER_TOOLS) == 4


def test_ticker_tools_have_expected_names() -> None:
    names = {t.name for t in TICKER_TOOLS}
    assert names == {"tokenize", "completeness", "rank", "infer_code"}


# ============================================================
# 工具签名 smoke（detail behavior 见 test_tools_real.py）
# ============================================================


def test_tokenize_basic_invocation() -> None:
    """tokenize 至少能被空字符串调用并返回 list。"""
    assert tokenize.invoke({"raw_text": ""}) == []


def test_completeness_signature() -> None:
    """completeness 接收 keyword + 返回 dict（含 is_complete / candidates）。"""
    # 后端不可达时退化后缀规则（不触发 mock_api）
    result = completeness.invoke({"keyword": "00700.HK"})
    assert "is_complete" in result
    assert "keyword" in result


def test_rank_signature() -> None:
    """rank 接收 keyword（不再是 candidates list），返回含 winner/needs_hitl 的 dict。"""
    result = rank.invoke({"keyword": ""})
    assert "winner" in result
    assert "needs_hitl" in result
    assert "candidates" in result


def test_infer_code_signature() -> None:
    """infer_code 接收 keyword 返回 str。空输入短路。"""
    assert infer_code.invoke({"keyword": ""}) == ""


# ============================================================
# 子图编译（不调 LLM，仅验证 build_ticker_graph 不抛异常）
# ============================================================


def test_ticker_graph_compiles() -> None:
    """ticker 子图能成功编译。"""
    from app.subgraphs.ticker.graph import build_ticker_graph

    graph = build_ticker_graph()
    assert graph is not None
