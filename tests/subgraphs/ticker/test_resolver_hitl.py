"""ticker resolver HITL 行为测试（Issue #20）。

覆盖：
- resolve_ticker_full 返回 TickerResolution（resolved + hitl_pending）
- 多命中分差 < GAP → hitl_pending 收集候选，resolved 为空（此 keyword）
- 多命中分差 ≥ GAP → 自动选 top1，hitl_pending 无此 keyword
- 0 命中 → hitl_pending 为空，resolved 也为空（无兜底时返回 []）
- 混合 keyword：部分可解析、部分 HITL → 分别归类
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.ticker import resolver as resolver_mod
from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.resolver import TickerResolution, resolve_ticker_full
from app.tools.ticker_client import SecuritiesInstrumentRespVO


@pytest.fixture(autouse=True)
def _force_react_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver_mod, "DEFAULT_MODE", "react")


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
# 多命中 gap ≥ 10 → 自动选 top1，不进 hitl_pending
# ============================================================


@pytest.mark.asyncio
async def test_multi_match_large_gap_auto_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(
        monkeypatch,
        {
            "茅台": [
                _resp("600519.SH", "贵州茅台", 0),   # top1 score=0
                _resp("600079.SH", "华润医药", 15),   # gap=15 ≥ 10
            ]
        },
    )
    result = await resolve_ticker_full("茅台")
    assert len(result.resolved) == 1
    assert result.resolved[0].windCode == "600519.SH"
    assert result.hitl_pending == []


# ============================================================
# 多命中 gap < 10 → 进 hitl_pending，不进 resolved
# ============================================================


@pytest.mark.asyncio
async def test_multi_match_small_gap_triggers_hitl(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(
        monkeypatch,
        {
            "腾讯": [
                _resp("00700.HK", "腾讯控股", 0),
                _resp("TME.N", "腾讯音乐", 5),  # gap=5 < 10
            ]
        },
    )
    result = await resolve_ticker_full("腾讯")
    assert result.resolved == []
    assert len(result.hitl_pending) == 1
    pending = result.hitl_pending[0]
    assert pending["keyword"] == "腾讯"
    assert len(pending["candidates"]) == 2
    assert pending["candidates"][0]["windCode"] == "00700.HK"
    assert pending["candidates"][1]["windCode"] == "TME.N"


# ============================================================
# 0 命中 → resolved 和 hitl_pending 均为空
# ============================================================


@pytest.mark.asyncio
async def test_zero_match_no_resolved_no_hitl(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, {})  # 任何 keyword 都返回 []
    result = await resolve_ticker_full("XYZ不存在的标的")
    assert result.resolved == []
    assert result.hitl_pending == []


# ============================================================
# 混合场景：一个 keyword 可解析 + 一个触发 HITL
# ============================================================


@pytest.mark.asyncio
async def test_mixed_resolved_and_hitl(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(
        monkeypatch,
        {
            "600519": [_resp("600519.SH", "贵州茅台", 0)],  # 单命中 → resolved
            "腾讯": [
                _resp("00700.HK", "腾讯控股", 0),
                _resp("TME.N", "腾讯音乐", 3),  # gap=3 < 10 → HITL
            ],
        },
    )
    result = await resolve_ticker_full("600519 腾讯")
    assert len(result.resolved) == 1
    assert result.resolved[0].windCode == "600519.SH"
    assert len(result.hitl_pending) == 1
    assert result.hitl_pending[0]["keyword"] == "腾讯"


# ============================================================
# hitl_pending 候选字段结构
# ============================================================


@pytest.mark.asyncio
async def test_hitl_pending_candidate_structure(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert result.hitl_pending
    c0 = result.hitl_pending[0]["candidates"][0]
    assert "windCode" in c0
    assert "insShtDesc" in c0


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
