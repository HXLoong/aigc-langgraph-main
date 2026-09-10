"""3 路批量 LLM 调用 + rank 单测（infer_code_batch / split_ticker_keywords /
judge_ticker_type / rank_candidates）。全部 mock `get_qwen_standard`，不联网。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.tools import (
    infer_code_batch,
    judge_ticker_type,
    rank_candidates,
    split_ticker_keywords,
)


def _fake_llm(content: str) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=content))
    return llm


# ============================================================
# 空输入短路（不调 LLM）
# ============================================================


@pytest.mark.asyncio
async def test_infer_code_batch_empty_candidates_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _fake_llm("")
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: llm)
    assert await infer_code_batch([]) == {}
    llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_split_ticker_keywords_empty_candidates_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _fake_llm("")
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: llm)
    assert await split_ticker_keywords([]) == {}
    llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_judge_ticker_type_empty_candidates_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _fake_llm("")
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: llm)
    assert await judge_ticker_type([]) == {}
    llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_rank_candidates_empty_results_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _fake_llm("")
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: llm)
    assert await rank_candidates("茅台", []) == []
    llm.ainvoke.assert_not_called()


# ============================================================
# infer_code_batch：<analysis>...<result>{...}</result> 格式解析
# ============================================================


@pytest.mark.asyncio
async def test_infer_code_batch_parses_result_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        "<analysis>\n"
        '"贵州茅台" → [600519.SH, 贵州茅台] |\n'
        "</analysis>\n"
        "<result>\n"
        '{"贵州茅台": ["600519.SH", "贵州茅台"]}\n'
        "</result>"
    )
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: _fake_llm(content))
    result = await infer_code_batch(["贵州茅台"])
    assert result == {"贵州茅台": ["600519.SH", "贵州茅台"]}


@pytest.mark.asyncio
async def test_infer_code_batch_malformed_output_returns_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: _fake_llm("不是 JSON 也没有 result 标签"))
    result = await infer_code_batch(["贵州茅台"])
    assert result == {}


@pytest.mark.asyncio
async def test_infer_code_batch_llm_exception_returns_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=ConnectionError("backend down"))
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: llm)
    result = await infer_code_batch(["贵州茅台"])
    assert result == {}


# ============================================================
# split_ticker_keywords / judge_ticker_type：纯 JSON（可能带 markdown fence）
# ============================================================


@pytest.mark.asyncio
async def test_split_ticker_keywords_parses_plain_json(monkeypatch: pytest.MonkeyPatch) -> None:
    content = '{"02513智谱": ["02513", "智谱"]}'
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: _fake_llm(content))
    result = await split_ticker_keywords(["02513智谱"])
    assert result == {"02513智谱": ["02513", "智谱"]}


@pytest.mark.asyncio
async def test_split_ticker_keywords_strips_markdown_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = '```json\n{"02513智谱": ["02513", "智谱"]}\n```'
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: _fake_llm(content))
    result = await split_ticker_keywords(["02513智谱"])
    assert result == {"02513智谱": ["02513", "智谱"]}


@pytest.mark.asyncio
async def test_judge_ticker_type_parses_plain_json(monkeypatch: pytest.MonkeyPatch) -> None:
    content = '{"贵州茅台": "EQUITY", "沪深300ETF": "FUND"}'
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: _fake_llm(content))
    result = await judge_ticker_type(["贵州茅台", "沪深300ETF"])
    assert result == {"贵州茅台": "EQUITY", "沪深300ETF": "FUND"}


# ============================================================
# rank_candidates：<result>[...]</result> array 解析
# ============================================================


class _FakeCandidate:
    def __init__(self, wind_code: str, sht: str = "") -> None:
        self.wind_code = wind_code
        self.ins_sht_desc = sht
        self.ins_lng_desc = sht
        self.relevance_score = 0
        self.transaction_type_lists: list[str] = []


@pytest.mark.asyncio
async def test_rank_candidates_parses_result_array(monkeypatch: pytest.MonkeyPatch) -> None:
    content = '<result>\n["600519.SH", "000858.SZ"]\n</result>'
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: _fake_llm(content))
    results = [_FakeCandidate("000858.SZ"), _FakeCandidate("600519.SH")]
    ranked = await rank_candidates("贵州茅台", results)
    assert ranked == ["600519.SH", "000858.SZ"]


@pytest.mark.asyncio
async def test_rank_candidates_malformed_output_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: _fake_llm("啊这不是 JSON"))
    results = [_FakeCandidate("600519.SH")]
    ranked = await rank_candidates("贵州茅台", results)
    assert ranked == []


@pytest.mark.asyncio
async def test_rank_candidates_single_result_still_calls_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rank_candidates 本身对"单结果"不做特殊短路（该优化在 resolver 层做）。"""
    content = '<result>\n["600519.SH"]\n</result>'
    llm = _fake_llm(content)
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: llm)
    ranked = await rank_candidates("贵州茅台", [_FakeCandidate("600519.SH")])
    assert ranked == ["600519.SH"]
    llm.ainvoke.assert_called_once()
