"""ticker resolver 接口测试（白名单模式 — env TICKER_RESOLVER_MODE=whitelist）。

ReAct 模式测试见 test_resolver_react.py。
"""
from __future__ import annotations

import pytest

from app.subgraphs.ticker import resolver as resolver_mod
from app.subgraphs.ticker.resolver import resolve_ticker
from app.subgraphs.ticker.whitelist import TICKER_WHITELIST


@pytest.fixture(autouse=True)
def _force_whitelist_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有本文件测试强制走白名单（与原行为一致）。"""
    monkeypatch.setattr(resolver_mod, "DEFAULT_MODE", "whitelist")


# ============================================================
# 白名单数据完整性
# ============================================================


class TestWhitelistData:
    def test_whitelist_size_around_50(self) -> None:
        """白名单含原始条目 + 自动生成的 code→code 反向映射，规模 40-120。"""
        assert 40 <= len(TICKER_WHITELIST) <= 120

    def test_all_wind_codes_have_suffix(self) -> None:
        """所有 wind 代码必须含交易所后缀（.HK / .SH / .SZ / .O / .GI 等）。"""
        for keyword, (code, _) in TICKER_WHITELIST.items():
            assert "." in code, f"{keyword} 的 windCode '{code}' 缺后缀"

    def test_short_desc_not_empty(self) -> None:
        for keyword, (_, sht_desc) in TICKER_WHITELIST.items():
            assert sht_desc, f"{keyword} 的简称为空"


# ============================================================
# resolve_ticker 接口契约
# ============================================================


@pytest.mark.asyncio
class TestResolveTickerInterface:
    async def test_empty_input_returns_empty(self) -> None:
        assert await resolve_ticker("") == []

    async def test_no_match_returns_empty(self) -> None:
        """0 命中 → 空 list（触发 cascade 防御 + fallback，ADR 0008 b）。"""
        result = await resolve_ticker("莫名其妙的输入")
        assert result == []

    async def test_single_keyword_match(self) -> None:
        result = await resolve_ticker("做一笔腾讯的 TRS")
        assert len(result) == 1
        assert result[0].windCode == "00700.HK"
        assert result[0].from_goats is True
        assert result[0].relevanceScore == 100

    async def test_keyword_alias_matches_same_wind_code(self) -> None:
        """'腾讯' 和 '腾讯控股' 都指向 00700.HK，单关键词触发只一条。"""
        result_short = await resolve_ticker("腾讯")
        result_long = await resolve_ticker("腾讯控股")
        assert result_short[0].windCode == "00700.HK"
        assert result_long[0].windCode == "00700.HK"

    async def test_multi_match_dedupes_by_wind_code(self) -> None:
        """同一 windCode 多关键词命中只保留 1 条（如同时含'腾讯'和'腾讯控股'）。"""
        result = await resolve_ticker("买 腾讯 和 腾讯控股")
        wind_codes = [c.windCode for c in result]
        assert wind_codes.count("00700.HK") == 1

    async def test_multi_distinct_tickers(self) -> None:
        """g003 真实 case：'同时买入贵州茅台、腾讯各 100 股' 应返回 2 条。"""
        result = await resolve_ticker("同时买入贵州茅台、腾讯各 100 股")
        wind_codes = {c.windCode for c in result}
        assert "600519.SH" in wind_codes  # 贵州茅台
        assert "00700.HK" in wind_codes  # 腾讯


# ============================================================
# 覆盖 golden 中的具体标的
# ============================================================


@pytest.mark.asyncio
class TestGoldenTickerCoverage:
    """白名单应能命中 golden.jsonl 提到的标的。"""

    async def test_g001_招商银行(self) -> None:
        result = await resolve_ticker("做一笔招商银行的 TRS，买 1000 手")
        assert any(c.windCode == "600036.SH" for c in result)

    async def test_g002_腾讯控股(self) -> None:
        result = await resolve_ticker("互换下单 帮我买入1000股腾讯控股")
        assert any(c.windCode == "00700.HK" for c in result)

    async def test_g010_纳指(self) -> None:
        result = await resolve_ticker("做 纳指 一笔互换")
        assert any(c.windCode == "NDX.GI" for c in result)

    async def test_g012_腾讯_option(self) -> None:
        result = await resolve_ticker("参与型看涨 腾讯控股 1个月")
        assert any(c.windCode == "00700.HK" for c in result)

    async def test_g013_阿里巴巴(self) -> None:
        result = await resolve_ticker("参与型看跌 阿里巴巴 3个月")
        assert any(c.windCode == "09988.HK" for c in result)

    async def test_g015_茅台(self) -> None:
        result = await resolve_ticker("帮我询价茅台 3 个月雪球 名义 1000w")
        assert any(c.windCode == "600519.SH" for c in result)

    async def test_g017_茅台_place(self) -> None:
        result = await resolve_ticker(
            "期权下单 茅台 欧式看涨 行权价 1800 期限 1M 名义 500万"
        )
        assert any(c.windCode == "600519.SH" for c in result)


# ============================================================
# from_goats 硬约束（CLAUDE.md）
# ============================================================


@pytest.mark.asyncio
async def test_all_returned_candidates_have_from_goats_true() -> None:
    """CLAUDE.md 硬约束：任何输出标的必须 from_goats=True。"""
    result = await resolve_ticker("买入腾讯、茅台、纳指")
    assert len(result) >= 1
    for c in result:
        assert c.from_goats is True
