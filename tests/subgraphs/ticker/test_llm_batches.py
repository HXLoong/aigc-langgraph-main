"""3 路批量 LLM 调用 + rank 单测（infer_code_batch / split_ticker_keywords /
judge_ticker_type / rank_candidates）。

ADR 0022 未决项（ticker 4 提示词转 structured output）后为结构化路径：
mock `get_qwen_standard` 返回替身，ainvoke 返回契约模型实例
（app/subgraphs/ticker/models.py，映射类输出统一包在 results 锚点字段下），不联网。
"""
from __future__ import annotations

from typing import Any
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
    """structured output 链路替身：ainvoke 返回契约模型实例，异常路径用 side_effect 模拟。"""

    def __init__(
        self, *, outcomes: list[Any] | None = None, error: Exception | None = None
    ) -> None:
        if error is not None:
            self.ainvoke = AsyncMock(side_effect=error)
        else:
            self.ainvoke = AsyncMock(side_effect=outcomes if outcomes is not None else [None])
        self.models: list[object] = []

    def with_structured_output(self, model: object, **kwargs: Any) -> _FakeStructuredLLM:
        self.models.append(model)
        return self


def _install(
    monkeypatch: pytest.MonkeyPatch,
    output: object | None = None,
    *,
    error: Exception | None = None,
    outcomes: list[Any] | None = None,
) -> _FakeStructuredLLM:
    resolved = outcomes if outcomes is not None else [output]
    fake = _FakeStructuredLLM(outcomes=resolved, error=error)
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
async def test_infer_code_batch_returns_contract_model_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = InferCodeOutput.model_validate(
        {"results": {"贵州茅台": ["600519.SH", "贵州茅台"]}}
    )
    fake = _install(monkeypatch, output)
    result = await infer_code_batch(["贵州茅台"])
    assert result == {"贵州茅台": ["600519.SH", "贵州茅台"]}
    assert fake.models == [InferCodeOutput]


@pytest.mark.asyncio
async def test_infer_code_batch_validation_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, error=ValueError("OutputParserException"))
    with pytest.raises(ValueError):
        await infer_code_batch(["贵州茅台"])
    assert fake.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_infer_code_batch_llm_exception_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, error=ConnectionError("backend down"))
    with pytest.raises(ConnectionError):
        await infer_code_batch(["贵州茅台"])
    assert fake.ainvoke.await_count == 1


# ============================================================
# split_ticker_keywords / judge_ticker_type：structured output（契约模型 → dict）
# ============================================================


@pytest.mark.asyncio
async def test_split_ticker_keywords_returns_contract_model_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = SplitKeywordsOutput.model_validate({"results": {"02513智谱": ["02513", "智谱"]}})
    fake = _install(monkeypatch, output)
    result = await split_ticker_keywords(["02513智谱"])
    assert result == {"02513智谱": ["02513", "智谱"]}
    assert fake.models == [SplitKeywordsOutput]


@pytest.mark.asyncio
async def test_judge_ticker_type_returns_contract_model_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = JudgeTypeOutput.model_validate(
        {"results": {"贵州茅台": "EQUITY", "沪深300ETF": "FUND"}}
    )
    fake = _install(monkeypatch, output)
    result = await judge_ticker_type(["贵州茅台", "沪深300ETF"])
    assert result == {"贵州茅台": "EQUITY", "沪深300ETF": "FUND"}
    assert fake.models == [JudgeTypeOutput]


# ============================================================
# 解析失败重试一次（根修见 models.py：results 锚点消除 schema-echo 触发；本组守兜底语义）
# ============================================================


@pytest.mark.asyncio
async def test_helper_propagates_failure_and_next_graph_attempt_can_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    """首次解析失败（schema-echo 类）→ 重试一次成功，不降级。"""
    fake = _install(monkeypatch, outcomes=[
        ValueError("schema-echo"),
        JudgeTypeOutput.model_validate({"results": {"600519.SH": "EQUITY"}}),
    ])
    with pytest.raises(ValueError):
        await judge_ticker_type(["600519.SH"])
    assert fake.ainvoke.await_count == 1
    result = await judge_ticker_type(["600519.SH"])
    assert result == {"600519.SH": "EQUITY"}
    assert fake.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_helper_does_not_swallow_repeated_schema_failures(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """单次 helper 不重试或吞异常，图级 RetryPolicy 负责预算。"""
    fake = _install(monkeypatch, outcomes=[ValueError("schema-echo"), ValueError("schema-echo")])
    with pytest.raises(ValueError):
        await split_ticker_keywords(["600519.SH"])
    assert fake.ainvoke.await_count == 1


# ============================================================
# rank_candidates：structured output（RankOutput → list[str]）
# ============================================================


def _fake_candidate(wind_code: str, sht: str = "") -> dict:
    """GOATS 候选行（后端数据原样 dict 透传契约）。"""
    return {
        "windCode": wind_code,
        "insShtDesc": sht,
        "insLngDesc": sht,
        "relevanceScore": 0,
        "transactionTypeLists": [],
    }


@pytest.mark.asyncio
async def test_rank_candidates_returns_contract_model_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, RankOutput(ranked_codes=["600519.SH", "000858.SZ"]))
    results = [_fake_candidate("000858.SZ"), _fake_candidate("600519.SH")]
    ranked = await rank_candidates("贵州茅台", results)
    assert ranked == ["600519.SH", "000858.SZ"]
    assert fake.models == [RankOutput]


@pytest.mark.asyncio
async def test_rank_candidates_llm_error_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, error=RuntimeError("parse failed"))
    results = [_fake_candidate("600519.SH")]
    with pytest.raises(RuntimeError):
        await rank_candidates("贵州茅台", results)
    assert fake.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_rank_candidates_single_result_still_calls_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rank_candidates 本身对"单结果"不做特殊短路（该优化在 resolver 层做）。"""
    fake = _install(monkeypatch, RankOutput(ranked_codes=["600519.SH"]))
    ranked = await rank_candidates("贵州茅台", [_fake_candidate("600519.SH")])
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
    fake = _install(monkeypatch, InferCodeOutput.model_validate({"results": {}}))
    await infer_code_batch(["沪铜主力"])
    system = fake.ainvoke.call_args.args[0][0].content
    assert "{{current_date}}" not in system
    assert _today_zh() in system


@pytest.mark.asyncio
async def test_rank_system_has_current_date(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, RankOutput(ranked_codes=[]))
    await rank_candidates("沪铜", [_fake_candidate("CU2610.SHF")])
    system = fake.ainvoke.call_args.args[0][0].content
    assert "{{current_date}}" not in system
    assert _today_zh() in system
