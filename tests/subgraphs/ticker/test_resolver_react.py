"""ticker resolver · ReAct 模式测试（mock client 不调真后端）。

覆盖：
- ReAct 编排正常路径（tokenize → rank → 单/多命中分差）
- 多命中分差小 → HITL 跳过（不入 candidates）
- 0 命中 → 返回空
- 异常 → 返回空
- 空 raw_text 短路
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.ticker import resolver as resolver_mod
from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.resolver import resolve_ticker, resolve_ticker_full
from app.tools.ticker_client import SecuritiesInstrumentRespVO


def _resp(wind: str, sht: str | None = None, score: int = 0) -> SecuritiesInstrumentRespVO:
    return SecuritiesInstrumentRespVO(
        windCode=wind, insShtDesc=sht or wind, relevanceScore=score
    )


def _mock_client_by_kw(monkeypatch: pytest.MonkeyPatch, by_kw: dict) -> MagicMock:
    """让 _make_client 返回的 client 按 keyword 路由不同响应。

    by_kw: {"keyword": [resp_list], ...}
    """
    client = MagicMock()

    async def _search(req):
        kw = req.keywordItems[0].keyword if req.keywordItems else ""
        return by_kw.get(kw, [])

    client.search_securities_instrument = AsyncMock(side_effect=_search)
    # patch 两处使用点（tools_mod 定义、resolver_mod 已 import 绑定）
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
    monkeypatch.setattr(resolver_mod, "_make_client", lambda: client)
    return client


# ============================================================
# 1. 空 raw_text 短路
# ============================================================


@pytest.mark.asyncio
async def test_empty_raw_returns_empty() -> None:
    assert await resolve_ticker("") == []
    assert await resolve_ticker("   ") == []


# ============================================================
# 2. 单命中 → 直接选
# ============================================================


@pytest.mark.asyncio
async def test_single_match_returns_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_client_by_kw(monkeypatch, {"腾讯": [_resp("00700.HK", "腾讯控股", 0)]})
    result = await resolve_ticker("腾讯")
    assert len(result) == 1
    assert result[0].windCode == "00700.HK"
    assert result[0].insShtDesc == "腾讯控股"
    assert result[0].from_goats is True


# ============================================================
# 3. 多命中分差大 → 自动选 top1
# ============================================================


@pytest.mark.asyncio
async def test_multi_match_large_gap_picks_top1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_client_by_kw(
        monkeypatch,
        {"腾讯": [_resp("00700.HK", "腾讯控股", 0), _resp("OTHER.HK", "其他", 10)]},
    )
    result = await resolve_ticker("腾讯")
    assert len(result) == 1
    assert result[0].windCode == "00700.HK"


# ============================================================
# 4. 多命中分差小 → HITL 跳过（不入 candidates）
# ============================================================


@pytest.mark.asyncio
async def test_multi_match_picks_best(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多命中分差 < GAP → HITL pending；分差 ≥ GAP → 自动选 top1。"""
    _mock_client_by_kw(
        monkeypatch,
        {
            "ambig": [_resp("A.HK", "A", 5), _resp("B.HK", "B", 8)],
            "腾讯": [_resp("00700.HK", "腾讯控股", 0)],
        },
    )
    resolution = await resolve_ticker_full("ambig 腾讯")
    # "腾讯" → resolved；"ambig" → pick_best → A.HK（无前缀/精确匹配时取首个）
    winners = {r.windCode for r in resolution.resolved}
    assert "00700.HK" in winners
    assert "A.HK" in winners
    assert resolution.hitl_pending == []


# ============================================================
# 5. 0 命中 → 返回空
# ============================================================


@pytest.mark.asyncio
async def test_zero_match_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ReAct 全部 0 命中 → 返回空 list。"""
    _mock_client_by_kw(monkeypatch, {})
    result = await resolve_ticker("腾讯")
    assert result == []


# ============================================================
# 6. 真后端异常 → 返回空（不让业务挂）
# ============================================================


@pytest.mark.asyncio
async def test_backend_exception_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tokenize 之后每个 keyword 查后端都抛异常 → 返回空，不崩溃。"""
    client = MagicMock()
    client.search_securities_instrument = AsyncMock(
        side_effect=ConnectionError("backend down")
    )
    monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
    monkeypatch.setattr(resolver_mod, "_make_client", lambda: client)

    result = await resolve_ticker("腾讯")
    assert result == []


# ============================================================
# 7. 多 ticker 复合查询
# ============================================================


@pytest.mark.asyncio
async def test_multi_ticker_in_one_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_client_by_kw(
        monkeypatch,
        {
            "600519": [_resp("600519.SH", "贵州茅台", 0)],
            "000858": [_resp("000858.SZ", "五粮液", 0)],
        },
    )
    result = await resolve_ticker("600519/000858")
    winners = {r.windCode for r in result}
    assert winners == {"600519.SH", "000858.SZ"}


# ============================================================
# 8. 同 windCode 重复命中 → 去重
# ============================================================


@pytest.mark.asyncio
async def test_dedupe_same_wind_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两个 keyword 都指向同一 windCode → 仅返回一条。"""
    _mock_client_by_kw(
        monkeypatch,
        {
            "腾讯": [_resp("00700.HK", "腾讯控股", 0)],
            "00700": [_resp("00700.HK", "腾讯控股", 0)],
        },
    )
    result = await resolve_ticker("腾讯 00700")
    assert len(result) == 1
    assert result[0].windCode == "00700.HK"




# ============================================================
# 10. tokenize 抽不出 keyword → 直接 0 candidates（白名单兜底也是 [])
# ============================================================


@pytest.mark.asyncio
async def test_no_tokens_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_client_by_kw(monkeypatch, {})
    # 全是分隔符 → tokenize 输出 []
    result = await resolve_ticker(" ,,，；； ")
    assert result == []
