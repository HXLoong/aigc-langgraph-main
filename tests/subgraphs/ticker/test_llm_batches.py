"""3 路批量 LLM 调用 + rank 单测（infer_code_batch / split_ticker_keywords /
judge_ticker_type / rank_candidates）。

ADR 0022 未决项（ticker 4 提示词转 structured output）后为结构化路径：
mock `get_qwen_standard` 返回替身，第二次 ainvoke 返回契约模型实例
（app/subgraphs/ticker/models.py），不联网。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.models import (
    InferCodeOutput,
    JudgeTypeOutput,
    RankOutput,
    SplitKeywordsOutput,
)
from app.subgraphs.ticker.tools import (
    infer_code_batch,
    judge_ticker_type,
    rank_candidates,
    split_ticker_keywords,
)


class _FakeStructuredLLM:
    """structured output 链路替身：记录契约模型 + ainvoke 调用。"""

    def __init__(self, output: object | None = None, *, error: Exception | None = None) -> None:
        self.ainvoke = (
            AsyncMock(side_effect=error)
            if error is not None
            else AsyncMock(return_value=output)
        )
        self.models: list[object] = []

    def with_structured_output(self, model: object) -> _FakeStructuredLLM:
        self.models.append(model)
        return self


def _install(
    monkeypatch: pytest.MonkeyPatch,
    output: object | None = None,
    *,
    error: Exception | None = None,
) -> _FakeStructuredLLM:
    fake = _FakeStructuredLLM(output, error=error)
    monkeypatch.setattr(tools_mod, "get_qwen_standard", lambda: fake)
    return fake


# ============================================================
# 空输入短路（不调 LLM）
# ============================================================


@pytest.mark.asyncio
async def test_infer_code_batch_empty_candidates_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    assert await infer_code_batch([]) == {}
    assert fake.models == []
    fake.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_split_ticker_keywords_empty_candidates_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    assert await split_ticker_keywords([]) == {}
    assert fake.models == []
    fake.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_judge_ticker_type_empty_candidates_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    assert await judge_ticker_type([]) == {}
    assert fake.models == []
    fake.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_rank_candidates_empty_results_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch)
    assert await rank_candidates("茅台", []) == []
    assert fake.models == []
    fake.ainvoke.assert_not_called()


# ============================================================
# infer_code_batch：structured output（契约模型 → dict）
# ============================================================


@pytest.mark.asyncio
async def test_infer_code_batch_returns_contract_model_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = InferCodeOutput.model_validate({"贵州茅台": ["600519.SH", "贵州茅台"]})
    fake = _install(monkeypatch, output)
    result = await infer_code_batch(["贵州茅台"])
    assert result == {"贵州茅台": ["600519.SH", "贵州茅台"]}
    assert fake.models == [InferCodeOutput]


@pytest.mark.asyncio
async def test_infer_code_batch_validation_error_returns_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, error=ValueError("OutputParserException"))
    result = await infer_code_batch(["贵州茅台"])
    assert result == {}
    fake.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_infer_code_batch_llm_exception_returns_empty_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, error=ConnectionError("backend down"))
    result = await infer_code_batch(["贵州茅台"])
    assert result == {}
    fake.ainvoke.assert_called_once()


# ============================================================
# split_ticker_keywords / judge_ticker_type：structured output（契约模型 → dict）
# ============================================================


@pytest.mark.asyncio
async def test_split_ticker_keywords_returns_contract_model_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = SplitKeywordsOutput.model_validate({"02513智谱": ["02513", "智谱"]})
    fake = _install(monkeypatch, output)
    result = await split_ticker_keywords(["02513智谱"])
    assert result == {"02513智谱": ["02513", "智谱"]}
    assert fake.models == [SplitKeywordsOutput]


@pytest.mark.asyncio
async def test_judge_ticker_type_returns_contract_model_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = JudgeTypeOutput.model_validate({"贵州茅台": "EQUITY", "沪深300ETF": "FUND"})
    fake = _install(monkeypatch, output)
    result = await judge_ticker_type(["贵州茅台", "沪深300ETF"])
    assert result == {"贵州茅台": "EQUITY", "沪深300ETF": "FUND"}
    assert fake.models == [JudgeTypeOutput]


# ============================================================
# rank_candidates：structured output（RankOutput → list[str]）
# ============================================================


class _FakeCandidate:
    def __init__(self, wind_code: str, sht: str = "") -> None:
        self.wind_code = wind_code
        self.ins_sht_desc = sht
        self.ins_lng_desc = sht
        self.relevance_score = 0
        self.transaction_type_lists: list[str] = []


@pytest.mark.asyncio
async def test_rank_candidates_returns_contract_model_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, RankOutput(ranked_codes=["600519.SH", "000858.SZ"]))
    results = [_FakeCandidate("000858.SZ"), _FakeCandidate("600519.SH")]
    ranked = await rank_candidates("贵州茅台", results)
    assert ranked == ["600519.SH", "000858.SZ"]
    assert fake.models == [RankOutput]


@pytest.mark.asyncio
async def test_rank_candidates_llm_error_returns_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, error=RuntimeError("parse failed"))
    results = [_FakeCandidate("600519.SH")]
    ranked = await rank_candidates("贵州茅台", results)
    assert ranked == []
    fake.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_rank_candidates_single_result_still_calls_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rank_candidates 本身对"单结果"不做特殊短路（该优化在 resolver 层做）。"""
    fake = _install(monkeypatch, RankOutput(ranked_codes=["600519.SH"]))
    ranked = await rank_candidates("贵州茅台", [_FakeCandidate("600519.SH")])
    assert ranked == ["600519.SH"]
    fake.ainvoke.assert_called_once()


# ============================================================
# 提示词治理评估 TRJ-01：当前日期必须由代码注入（Dify 由 JS 节点注入，迁移时丢失）
# ============================================================


def _today_zh() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return f"{now.year}/{now.month}/{now.day}"


@pytest.mark.asyncio
async def test_infer_code_system_has_current_date(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, InferCodeOutput.model_validate({}))
    await infer_code_batch(["沪铜主力"])
    system = fake.ainvoke.call_args.args[0][0].content
    assert "1775913928411.date" not in system
    assert _today_zh() in system


@pytest.mark.asyncio
async def test_rank_system_has_current_date(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, RankOutput(ranked_codes=[]))
    await rank_candidates("沪铜", [_FakeCandidate("CU2610.SHF")])
    system = fake.ainvoke.call_args.args[0][0].content
    assert "{{#1775820054722.date#}}" not in system
    assert _today_zh() in system
