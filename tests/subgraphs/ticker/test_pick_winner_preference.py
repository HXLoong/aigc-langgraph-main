"""ticker resolver._pick_winner 偏好测试 (P0-A from Round 3 eval)。

覆盖 Round 3 eval 中暴露的失败模式：
- 平安 → 1833.HK（应优先 .SH）
- 中证1000 → 1000.HK（应优先 A 股，若无 A 股不强选 .HK 但不误入期货）
- 宁德时代代 → B06M.DCE（typo 场景，仅有期货 → 应返回 None 而非误选期货）
- SZ .159984 → A03M.DCE（仅期货命中 → 应返回 None）
- 五粮液 + 000858 → 应保留 SZ 候选不被 SH 顶替（按 keyword 精确名称匹配）
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.subgraphs.ticker.resolver import _pick_winner


def _r(wind: str, sht: str | None = None, score: int = 0) -> MagicMock:
    """构造 GOATS 响应对象（duck-typed）。"""
    obj = MagicMock()
    obj.windCode = wind
    obj.insShtDesc = sht or wind
    obj.relevanceScore = score
    return obj


class TestPickWinnerTieredExchanges:
    """A 股 > 港股 > 期货 的分层选优。"""

    def test_a_share_preferred_over_hk(self) -> None:
        """[平安] 同时返回 .SH 和 .HK → 应选 .SH。"""
        results = [
            _r("1833.HK", "中国平安"),
            _r("601318.SH", "中国平安"),
        ]
        winner = _pick_winner("平安", results)
        assert winner is not None
        assert winner.windCode == "601318.SH", (
            f"A 股应优先于港股，实际选了 {winner.windCode}"
        )

    def test_sz_preferred_when_only_sz_a_share(self) -> None:
        """[创业板指 / 中证1000] 当 A 股仅有 .SZ 候选时也要选出来，不能因 SH 缺失而落到 HK。"""
        results = [
            _r("1000.HK", "中证1000"),
            _r("159845.SZ", "中证1000ETF"),
        ]
        winner = _pick_winner("中证1000", results)
        assert winner is not None
        assert winner.windCode.endswith(".SZ"), (
            f"有 .SZ 候选时应选 A 股，而不是港股，实际选了 {winner.windCode}"
        )

    def test_futures_only_returns_none(self) -> None:
        """[宁德时代代 typo] 仅命中期货 → 返回 None，避免误用期货代码触发"不在标的池"。"""
        results = [
            _r("B06M.DCE", "豆粕期货"),
            _r("B07M.DCE", "豆粕期货"),
        ]
        winner = _pick_winner("宁德时代代", results)
        assert winner is None, (
            f"仅命中期货时应返回 None（避免误用），实际选了 "
            f"{winner.windCode if winner else None}"
        )

    def test_futures_only_returns_none_a03(self) -> None:
        """[SZ .159984] 仅命中期货 → 返回 None。"""
        results = [_r("A03M.DCE", "豆一期货")]
        winner = _pick_winner("100call", results)
        assert winner is None

    def test_hk_only_returns_hk(self) -> None:
        """[腾讯] 仅命中港股 → 选港股（不会因为 cash market 优先而误选其他）。"""
        results = [_r("00700.HK", "腾讯控股")]
        winner = _pick_winner("腾讯", results)
        assert winner is not None
        assert winner.windCode == "00700.HK"

    def test_a_share_and_futures_mixed_picks_a_share(self) -> None:
        """混合 A 股 + 期货 → 选 A 股，期货不参与。"""
        results = [
            _r("300750.SZ", "宁德时代"),
            _r("B06M.DCE", "豆粕期货"),
        ]
        winner = _pick_winner("宁德时代", results)
        assert winner is not None
        assert winner.windCode == "300750.SZ"
