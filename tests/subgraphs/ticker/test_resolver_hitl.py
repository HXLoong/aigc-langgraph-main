"""ticker resolver pick_best 行为测试。

覆盖：
- resolve_ticker_full 返回 TickerResolution（resolved + hitl_pending 永远为空）
- 单命中 → resolved 有值
- 多命中 → pick_best 自动选优（精确匹配 > 前缀最短 > A股优先）
- 0 命中 → resolved 为空
- 混合 keyword：各自独立选优后合并到 resolved
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.ticker import resolver as resolver_mod
from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.resolver import TickerResolution, resolve_ticker_full
from app.tools.ticker_client import SecuritiesInstrumentRespVO


def _resp(wind: str, sht: str | None = None, score: int = 0) -> SecuritiesInstrumentRespVO:
    return SecuritiesInstrumentRespVO(
        windCode=wind, insShtDesc=sht or wind, relevanceScore=score
    )


def _mock_client(monkeypatch: pytest.MonkeyPatch, by_kw: dict) -> MagicMock:
    client = MagicMock()

    async def _search(req):
        kw = req.keywordItems[0].keyword if req.keywordItems else ""
        return by_kw.get(kw, [])

    client.search_securities_instrument = AsyncMock(side_effect=_search)
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
    monkeypatch.setattr(resolver_mod, "_make_client", lambda: client)
    return client


# ============================================================
# TickerResolution 接口契约
# ============================================================


def test_ticker_resolution_is_named_tuple() -> None:
    """TickerResolution 有 resolved 和 hitl_pending 两个字段。"""
    r = TickerResolution(resolved=[], hitl_pending=[])
    assert hasattr(r, "resolved")
    assert hasattr(r, "hitl_pending")


@pytest.mark.asyncio
async def test_empty_raw_returns_empty_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, {})
    result = await resolve_ticker_full("")
    assert isinstance(result, TickerResolution)
    assert result.resolved == []
    assert result.hitl_pending == []


# ============================================================
# 单命中 → resolved 有值，hitl_pending 为空
# ============================================================


@pytest.mark.asyncio
async def test_single_match_goes_to_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, {"茅台": [_resp("600519.SH", "贵州茅台", 0)]})
    result = await resolve_ticker_full("茅台")
    assert len(result.resolved) == 1
    assert result.resolved[0].windCode == "600519.SH"
    assert result.hitl_pending == []


# ============================================================
# 多命中 → pick_best A股优先选出最优
# ============================================================


@pytest.mark.asyncio
async def test_multi_match_a_share_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(
        monkeypatch,
        {
            "茅台": [
                _resp("600519.SH", "贵州茅台", 0),
                _resp("600079.SH", "华润医药", 15),
            ]
        },
    )
    result = await resolve_ticker_full("茅台")
    assert len(result.resolved) == 1
    assert result.resolved[0].windCode == "600519.SH"
    assert result.hitl_pending == []


@pytest.mark.asyncio
async def test_multi_match_prefix_hk_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    """前缀匹配同长度时 .HK 优先（港股 ETF 场景）。"""
    _mock_client(
        monkeypatch,
        {
            "腾讯": [
                _resp("00700.HK", "腾讯控股", 0),
                _resp("TME.N", "腾讯音乐", 5),
            ]
        },
    )
    result = await resolve_ticker_full("腾讯")
    assert len(result.resolved) == 1
    assert result.resolved[0].windCode == "00700.HK"
    assert result.hitl_pending == []


# ============================================================
# 0 命中 → resolved 和 hitl_pending 均为空
# ============================================================


@pytest.mark.asyncio
async def test_zero_match_no_resolved_no_hitl(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, {})
    result = await resolve_ticker_full("XYZ不存在的标的")
    assert result.resolved == []
    assert result.hitl_pending == []


# ============================================================
# 混合场景：多个 keyword 各自选优后合并
# ============================================================


@pytest.mark.asyncio
async def test_mixed_multi_keyword_all_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(
        monkeypatch,
        {
            "600519": [_resp("600519.SH", "贵州茅台", 0)],
            "腾讯": [
                _resp("00700.HK", "腾讯控股", 0),
                _resp("TME.N", "腾讯音乐", 3),
            ],
        },
    )
    result = await resolve_ticker_full("600519 腾讯")
    wind_codes = {r.windCode for r in result.resolved}
    assert "600519.SH" in wind_codes
    assert "00700.HK" in wind_codes
    assert result.hitl_pending == []


# ============================================================
# pick_best 选优：resolved 中的候选字段完整
# ============================================================


@pytest.mark.asyncio
async def test_resolved_candidate_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(
        monkeypatch,
        {
            "腾讯": [
                _resp("00700.HK", "腾讯控股", 0),
                _resp("TME.N", "腾讯音乐", 5),
            ]
        },
    )
    result = await resolve_ticker_full("腾讯")
    assert len(result.resolved) == 1
    assert result.resolved[0].windCode == "00700.HK"
    assert result.resolved[0].from_goats is True


# ============================================================
# resolve_ticker（旧接口）仍可正常返回 list[TickerCandidate]
# ============================================================


@pytest.mark.asyncio
async def test_resolve_ticker_backward_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_ticker 返回的仍是 list，不是 TickerResolution。"""
    from app.subgraphs.ticker.resolver import resolve_ticker

    _mock_client(monkeypatch, {"茅台": [_resp("600519.SH", "贵州茅台", 0)]})
    result = await resolve_ticker("茅台")
    assert isinstance(result, list)
    assert result[0].windCode == "600519.SH"
