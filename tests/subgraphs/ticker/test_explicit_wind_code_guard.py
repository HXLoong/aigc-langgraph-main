"""ticker resolver：用户输入完整 wind code 格式（XXXXXX.SH/SZ/BJ/HK）时不模糊回退。

Round C2 opt-016 暴露：用户输入 "999999.SH"（不存在的代码），GOATS 模糊搜索
返回 002001.SZ 新和成（无关结果），resolver 错误地选了 002001.SZ。

期望行为：keyword 是明确 wind code 格式 + GOATS 无精确匹配 → 返回 None（让上层走拒绝路径），
不要模糊回退到不相关的结果。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.subgraphs.ticker.resolver import _pick_winner


def _r(wind: str, desc: str = ""):
    return SimpleNamespace(windCode=wind, insShtDesc=desc)


class TestExplicitWindCodeGuard:
    """完整 wind code 模式不模糊回退。"""

    def test_999999_sh_with_irrelevant_results_returns_none(self) -> None:
        """999999.SH（不存在）+ GOATS 返回 002001.SZ → None，不模糊匹配。"""
        results = [_r("002001.SZ", "新和成")]
        winner = _pick_winner("999999.SH", results)
        assert winner is None, (
            f"完整 wind code 无精确匹配应返回 None，实际: {winner!r}"
        )

    def test_999999_sh_with_exact_match_returns_match(self) -> None:
        """如果 GOATS 真返回 999999.SH 精确匹配（理论上不可能但兜底）→ 返回。"""
        results = [_r("999999.SH", "测试")]
        winner = _pick_winner("999999.SH", results)
        assert winner is not None
        assert winner.windCode == "999999.SH"

    def test_partial_keyword_still_uses_fuzzy(self) -> None:
        """部分关键词（如裸名称"新和成"）仍允许模糊匹配，不改变现有行为。"""
        results = [_r("002001.SZ", "新和成")]
        winner = _pick_winner("新和成", results)
        assert winner is not None
        assert winner.windCode == "002001.SZ"

    def test_explicit_hk_code_no_match_returns_none(self) -> None:
        """港股完整 wind code 无精确匹配 → None。"""
        results = [_r("00700.HK", "腾讯控股")]
        winner = _pick_winner("99999.HK", results)
        assert winner is None
