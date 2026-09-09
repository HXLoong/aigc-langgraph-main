"""resolve_ticker_full / resolve_ticker 新管线黑盒测试（Dify DSL v2 迁移）。

只 mock 管线的三个边界：3 路批量 LLM（infer_code_batch / split_ticker_keywords /
judge_ticker_type）、rank_candidates（LLM 排序）、GOATS search_securities_instrument
（TickerClient）。不关心内部实现细节，只验证 resolve_ticker_full 的公开契约：

- 对外签名 `resolve_ticker_full(raw_text: str) -> TickerResolution` 不变
- from_goats=True 硬约束（ADR 0008）
- 空输入 / 0 命中 / 异常均不抛出，降级返回空结果
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.ticker import resolver as resolver_mod
from app.subgraphs.ticker.resolver import TickerResolution, resolve_ticker, resolve_ticker_full


class _FakeInstrument:
    def __init__(
        self,
        wind_code: str,
        sht: str = "",
        lng: str = "",
        score: int = 0,
        tx_types: list[str] | None = None,
    ) -> None:
        self.windCode = wind_code
        self.insShtDesc = sht
        self.insLngDesc = lng
        self.relevanceScore = score
        self.transactionTypeLists = tx_types or []


def _patch_llm_batches(
    monkeypatch: pytest.MonkeyPatch,
    infer: dict | None = None,
    split: dict | None = None,
    judge: dict | None = None,
) -> None:
    monkeypatch.setattr(
        resolver_mod, "infer_code_batch", AsyncMock(return_value=infer or {})
    )
    monkeypatch.setattr(
        resolver_mod, "split_ticker_keywords", AsyncMock(return_value=split or {})
    )
    monkeypatch.setattr(
        resolver_mod, "judge_ticker_type", AsyncMock(return_value=judge or {})
    )


def _patch_goats(monkeypatch: pytest.MonkeyPatch, results: list) -> None:
    from unittest.mock import MagicMock

    client = MagicMock()
    client.search_securities_instrument = AsyncMock(return_value=results)
    monkeypatch.setattr(resolver_mod, "_make_client", lambda: client)


# ============================================================
# 空输入 / 短路
# ============================================================


@pytest.mark.asyncio
async def test_same_instrument_merges_only_input_source_keywords(monkeypatch) -> None:
    _patch_llm_batches(monkeypatch, infer={
        "茅台": ["600519.SH"],
        "600519": ["600519.SH"],
        "invented-alias": ["600519.SH"],
    })
    _patch_goats(monkeypatch, [_FakeInstrument("600519.SH", "贵州茅台")])

    resolution = await resolve_ticker_full("茅台 600519")

    assert len(resolution.resolved) == 1
    ticker = resolution.resolved[0]
    assert ticker.windCode == "600519.SH"
    assert ticker.from_goats is True
    assert ticker.sourceKeywords == ["茅台", "600519"]


def test_old_ticker_checkpoint_defaults_to_no_source_keywords() -> None:
    from app.graph.state import TickerCandidate

    ticker = TickerCandidate.model_validate({"windCode": "600519.SH", "from_goats": True})
    assert ticker.sourceKeywords == []


@pytest.mark.asyncio
async def test_empty_raw_text_returns_empty_resolution() -> None:
    resolution = await resolve_ticker_full("")
    assert resolution == TickerResolution(resolved=[], hitl_pending=[])


@pytest.mark.asyncio
async def test_tenors_never_reach_inference_or_goats(monkeypatch) -> None:
    _patch_llm_batches(monkeypatch, infer={
        "600519.SH": ["600519.SH"], "600519": ["600519.SH"],
    })
    _patch_goats(monkeypatch, [_FakeInstrument("600519.SH")])

    result = await resolve_ticker_full("600519.SH,1M/2M,0.5y,80%")

    for batch in (resolver_mod.infer_code_batch, resolver_mod.split_ticker_keywords,
                  resolver_mod.judge_ticker_type):
        batch.assert_awaited_once_with(["600519.SH", "600519"])
    calls = resolver_mod._make_client().search_securities_instrument.call_args_list
    assert calls
    assert all(
        item.keyword == "600519.SH"
        for call in calls for item in call.args[0].keywordItems
    )
    assert [ticker.windCode for ticker in result.resolved] == ["600519.SH"]


@pytest.mark.asyncio
async def test_noise_only_input_short_circuits_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全是噪音候选（单字符/非4-6位数字）→ 候选列表为空，直接短路。"""
    infer_mock = AsyncMock(return_value={})
    monkeypatch.setattr(resolver_mod, "infer_code_batch", infer_mock)
    monkeypatch.setattr(resolver_mod, "split_ticker_keywords", AsyncMock(return_value={}))
    monkeypatch.setattr(resolver_mod, "judge_ticker_type", AsyncMock(return_value={}))

    resolution = await resolve_ticker_full("a b 12 33")

    assert resolution == TickerResolution(resolved=[], hitl_pending=[])
    infer_mock.assert_not_called()


# ============================================================
# 单命中：不走 rank
# ============================================================


@pytest.mark.asyncio
async def test_single_goats_hit_skips_rank_and_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_llm_batches(
        monkeypatch,
        infer={"贵州茅台": ["600519.SH", "贵州茅台"]},
        judge={"贵州茅台": "EQUITY"},
    )
    _patch_goats(monkeypatch, [_FakeInstrument("600519.SH", "贵州茅台")])
    rank_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(resolver_mod, "rank_candidates", rank_mock)

    resolution = await resolve_ticker_full("贵州茅台")

    assert len(resolution.resolved) == 1
    assert resolution.resolved[0].windCode == "600519.SH"
    assert resolution.resolved[0].from_goats is True
    rank_mock.assert_not_called()


# ============================================================
# 多命中：走 rank，按返回顺序取第一个能对上号的 windCode
# ============================================================


@pytest.mark.asyncio
async def test_multi_hit_uses_rank_to_pick_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm_batches(monkeypatch, infer={"腾讯": ["腾讯"]}, judge={"腾讯": "EQUITY"})
    _patch_goats(
        monkeypatch,
        [
            _FakeInstrument("00700.HK", "TENCENT"),
            _FakeInstrument("300750.SZ", "宁德时代（无关）"),
        ],
    )
    monkeypatch.setattr(
        resolver_mod, "rank_candidates", AsyncMock(return_value=["00700.HK"])
    )

    resolution = await resolve_ticker_full("腾讯")

    assert len(resolution.resolved) == 1
    assert resolution.resolved[0].windCode == "00700.HK"
    assert resolution.resolved[0].from_goats is True


@pytest.mark.asyncio
async def test_multi_hit_rank_returns_empty_skips_org_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rank 认为全部候选都不相关 → 该 orgStr 不产出任何标的（不臆造 fallback）。"""
    _patch_llm_batches(monkeypatch, infer={"腾讯": ["腾讯"]}, judge={"腾讯": "EQUITY"})
    _patch_goats(
        monkeypatch,
        [_FakeInstrument("00700.HK"), _FakeInstrument("300750.SZ")],
    )
    monkeypatch.setattr(resolver_mod, "rank_candidates", AsyncMock(return_value=[]))

    resolution = await resolve_ticker_full("腾讯")

    assert resolution.resolved == []


@pytest.mark.asyncio
async def test_rank_result_not_in_goats_candidates_skips_org_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rank 返回的 windCode 不在原始 GOATS 候选里（异常输出）→ 保守跳过，不硬凑。"""
    _patch_llm_batches(monkeypatch, infer={"腾讯": ["腾讯"]}, judge={"腾讯": "EQUITY"})
    _patch_goats(
        monkeypatch,
        [_FakeInstrument("00700.HK"), _FakeInstrument("300750.SZ")],
    )
    monkeypatch.setattr(
        resolver_mod, "rank_candidates", AsyncMock(return_value=["999999.SH"])
    )

    resolution = await resolve_ticker_full("腾讯")

    assert resolution.resolved == []


# ============================================================
# 0 命中
# ============================================================


@pytest.mark.asyncio
async def test_zero_goats_hit_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm_batches(monkeypatch, infer={"XYZNOMATCH": ["XYZNOMATCH"]})
    _patch_goats(monkeypatch, [])

    resolution = await resolve_ticker_full("XYZNOMATCH")

    assert resolution.resolved == []
    assert resolution.hitl_pending == []


# ============================================================
# 多 orgStr 去重
# ============================================================


@pytest.mark.asyncio
async def test_dedup_across_org_items_same_wind_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两个候选词都解析到同一个 windCode → resolved 里只留一份。"""
    _patch_llm_batches(
        monkeypatch,
        infer={"贵州茅台": ["600519.SH"], "600519": ["600519.SH"]},
    )

    async def _fake_search(req):
        return [_FakeInstrument("600519.SH", "贵州茅台")]

    from unittest.mock import MagicMock

    client = MagicMock()
    client.search_securities_instrument = AsyncMock(side_effect=_fake_search)
    monkeypatch.setattr(resolver_mod, "_make_client", lambda: client)
    monkeypatch.setattr(resolver_mod, "rank_candidates", AsyncMock(return_value=[]))

    resolution = await resolve_ticker_full("贵州茅台 600519")

    assert len(resolution.resolved) == 1
    assert resolution.resolved[0].windCode == "600519.SH"


# ============================================================
# 异常兜底
# ============================================================


@pytest.mark.asyncio
async def test_pipeline_exception_returns_empty_not_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resolver_mod,
        "infer_code_batch",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(resolver_mod, "split_ticker_keywords", AsyncMock(return_value={}))
    monkeypatch.setattr(resolver_mod, "judge_ticker_type", AsyncMock(return_value={}))

    resolution = await resolve_ticker_full("贵州茅台")

    assert resolution == TickerResolution(resolved=[], hitl_pending=[])


# ============================================================
# resolve_ticker() 向后兼容接口
# ============================================================


@pytest.mark.asyncio
async def test_resolve_ticker_returns_resolved_list_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_llm_batches(monkeypatch, infer={"贵州茅台": ["600519.SH"]})
    _patch_goats(monkeypatch, [_FakeInstrument("600519.SH", "贵州茅台")])
    monkeypatch.setattr(resolver_mod, "rank_candidates", AsyncMock(return_value=[]))

    tickers = await resolve_ticker("贵州茅台")

    assert len(tickers) == 1
    assert tickers[0].windCode == "600519.SH"
    assert tickers[0].from_goats is True
