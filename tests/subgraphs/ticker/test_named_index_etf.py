"""命名指数 → ETF 代码前置测试 (Round 3 eval P0-A 剩余 4 个失败)。

背景：场外期权后端的标的池只接受可交易 ETF（如 510050.SH），不接受指数代码（如 000016.SH）。
但 GOATS 对"上证50"/"创业板指"/"中证500"/"中证1000"/"沪深300"等命名指数关键词，
返回的是指数代码而非 ETF 代码。

修复：resolver 在 tokenize 之后，检测 raw_text 含已知命名指数 → 把对应 ETF 代码
**前置**到 keywords 队列首位，让 GOATS 先查 ETF 代码，结果 list 第一位 = ETF。
这样 option_extract_inquiry 的 order[0] 拿到 tickers[0].windCode 即 ETF，可通过后端校验。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.ticker import resolver as resolver_mod
from app.subgraphs.ticker import tools as tools_mod
from app.subgraphs.ticker.resolver import resolve_ticker_full
from app.tools.ticker_client import SecuritiesInstrumentRespVO


def _r(wind: str, sht: str | None = None, score: int = 0) -> SecuritiesInstrumentRespVO:
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


@pytest.mark.asyncio
class TestNamedIndexToEtf:
    """已知命名指数 → ETF 代码前置。"""

    async def test_zhongzheng_1000_resolves_to_etf_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """中证1000 → tickers[0] = 512100.SH（中证1000ETF），而非 1000.HK。"""
        _mock_client(
            monkeypatch,
            {
                "512100.SH": [_r("512100.SH", "中证1000ETF南方")],
                "1000": [_r("1000.HK", "古洞综合发展有限公司")],
                "中证": [],
                "100%": [],
                "2M": [],
            },
        )
        r = await resolve_ticker_full("中证1000 100% 2M")
        assert len(r.resolved) >= 1
        assert r.resolved[0].windCode == "512100.SH", (
            f"中证1000 应优先解析为 ETF 512100.SH，实际 resolved[0] = {r.resolved[0].windCode}"
        )

    async def test_chuangyeban_zhi_resolves_to_etf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """创业板指 → tickers[0] = 159915.SZ（创业板 ETF）。"""
        _mock_client(
            monkeypatch,
            {
                "159915.SZ": [_r("159915.SZ", "创业板ETF易方达")],
                "创业板指": [_r("399006.SZ", "创业板指")],
                "100%": [],
                "3M": [],
            },
        )
        r = await resolve_ticker_full("创业板指 100% 3M")
        assert len(r.resolved) >= 1
        assert r.resolved[0].windCode == "159915.SZ", (
            f"创业板指 应优先 ETF 159915.SZ，实际 {r.resolved[0].windCode}"
        )

    async def test_shangzheng_50_resolves_to_etf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """上证50 → tickers[0] = 510050.SH。"""
        _mock_client(
            monkeypatch,
            {
                "510050.SH": [_r("510050.SH", "上证50ETF华夏")],
                "上证": [],
                "50": [_r("000050.SZ", "深天马A")],
                "100%": [],
                "3M": [],
            },
        )
        r = await resolve_ticker_full("上证50 100% 3M")
        assert len(r.resolved) >= 1
        assert r.resolved[0].windCode == "510050.SH"

    async def test_zhongzheng_500_resolves_to_etf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """中证500 → tickers[0] = 510500.SH。"""
        _mock_client(
            monkeypatch,
            {
                "510500.SH": [_r("510500.SH", "中证500ETF南方")],
                "中证": [],
                "500": [_r("000822.SH", "海泰发展")],
                "100%": [],
                "3M": [],
            },
        )
        r = await resolve_ticker_full("中证500 100% 3M")
        assert len(r.resolved) >= 1
        assert r.resolved[0].windCode == "510500.SH"

    async def test_no_named_index_returns_normal_tokenize(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """raw_text 不含已知指数名 → 走正常 tokenize 路径（不引入 ETF 噪音）。"""
        _mock_client(
            monkeypatch,
            {"600519": [_r("600519.SH", "贵州茅台")]},
        )
        r = await resolve_ticker_full("600519")
        assert r.resolved[0].windCode == "600519.SH"

    async def test_hushen_300_resolves_to_etf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """沪深300 → tickers[0] = 510300.SH。"""
        _mock_client(
            monkeypatch,
            {
                "510300.SH": [_r("510300.SH", "沪深300ETF华泰柏瑞")],
                "沪深": [],
                "300": [],
                "100%": [],
                "3M": [],
            },
        )
        r = await resolve_ticker_full("沪深300 100% 3M")
        assert len(r.resolved) >= 1
        assert r.resolved[0].windCode == "510300.SH"
