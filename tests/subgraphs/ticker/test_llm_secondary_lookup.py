"""resolver LLM 二次校验测试（P0-A 升级：用 infer_code + GOATS 校验代替硬编码映射）。

设计：
1. resolver 主查询 GOATS
2. 对名称类 keyword（含中文字符），并行 / 额外调 infer_code LLM 推断 windCode
3. 若 LLM 推断的 windCode 不在主查询结果里 → 用该 windCode 做二次 GOATS 校验
4. 若二次校验有结果 → 用 LLM 推断的 windCode 作为 winner（**LLM 推断 + 后端权威源校验**）

覆盖 Round 4 eval 失败：
- 平安 → primary 000001.SZ（平安银行）, LLM 推断 601318.SH（中国平安）→ 二次校验 → 使用 601318.SH
- 五粮液000858 → 主流 keyword 解析顺序导致 000858.SH, LLM 推断 000858.SZ → 校验 → 使用 000858.SZ
- 宁德时代代（typo）→ primary [], LLM 纠错为 300750.SZ → 校验 → 使用 300750.SZ
- 中证500/中证1000 → primary 无 ETF, LLM 推断 ETF → 校验 → 使用 ETF
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


def _mock_infer_code(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str]) -> None:
    """mock infer_code 工具按 keyword → windCode 返回。"""
    def _fake(input_data):  # type: ignore[no-untyped-def]
        kw = input_data.get("keyword", "") if isinstance(input_data, dict) else str(input_data)
        return mapping.get(kw, kw)

    fake_tool = MagicMock()
    fake_tool.invoke = MagicMock(side_effect=_fake)
    monkeypatch.setattr(resolver_mod, "infer_code", fake_tool)


@pytest.mark.asyncio
class TestLLMSecondaryLookup:
    """LLM 二次校验：GOATS 主查 + infer_code 推断 + GOATS 校验。"""

    async def test_pingan_uses_llm_inferred_a_share(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """平安：primary GOATS 返回 000001.SZ（平安银行），LLM 推断 601318.SH（中国平安）。
        二次 GOATS 校验 601318.SH 存在 → 使用 LLM 答案。"""
        _mock_client(
            monkeypatch,
            {
                "平安": [
                    _r("1833.HK", "平安好医生"),
                    _r("000001.SZ", "平安银行"),
                ],
                "601318.SH": [_r("601318.SH", "中国平安")],
                "call": [],
                "100call": [],
                "3M": [],
            },
        )
        _mock_infer_code(monkeypatch, {"平安": "601318.SH"})

        r = await resolve_ticker_full("平安 100call 3M")
        codes = [c.windCode for c in r.resolved]
        assert "601318.SH" in codes, (
            f"应使用 LLM 推断的 601318.SH（中国平安），实际 resolved={codes}"
        )
        # 平安银行不应再出现在 resolved 首位
        assert codes[0] == "601318.SH", (
            f"LLM 推断的中国平安应优先于平安银行，实际 resolved[0]={codes[0]}"
        )

    async def test_typo_corrected_via_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """宁德时代代（typo）：primary GOATS 返回空，LLM 纠错为 300750.SZ → 校验 → 使用。"""
        _mock_client(
            monkeypatch,
            {
                "宁德时代代": [],  # typo → GOATS 找不到
                "300750.SZ": [_r("300750.SZ", "宁德时代")],
                "call": [],
                "100call": [],
                "6M": [],
            },
        )
        _mock_infer_code(monkeypatch, {"宁德时代代": "300750.SZ"})

        r = await resolve_ticker_full("宁德时代代 100call 6M")
        codes = [c.windCode for c in r.resolved]
        assert "300750.SZ" in codes, (
            f"typo 应被 LLM 纠错为宁德时代 300750.SZ，实际 resolved={codes}"
        )

    async def test_zhongzheng_500_etf_via_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """中证500：primary GOATS 返回指数代码（000822.SH），LLM 推断 ETF 510500.SH → 校验 → 使用。"""
        _mock_client(
            monkeypatch,
            {
                "中证500": [_r("000822.SH", "中证500红利")],
                "510500.SH": [_r("510500.SH", "中证500ETF南方")],
                "100%": [],
                "3M": [],
            },
        )
        _mock_infer_code(monkeypatch, {"中证500": "510500.SH"})

        r = await resolve_ticker_full("中证500 100% 3M")
        codes = [c.windCode for c in r.resolved]
        assert "510500.SH" in codes
        assert codes[0] == "510500.SH"

    async def test_pure_digit_code_not_consulted_with_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """纯数字代码 keyword："600519" → primary 命中即用，不浪费 LLM 调用。

        若 LLM mock 未被调用，说明我们正确跳过了名称类判断。
        """
        _mock_client(
            monkeypatch,
            {"600519": [_r("600519.SH", "贵州茅台")]},
        )
        fake_tool = MagicMock()
        fake_tool.invoke = MagicMock(return_value="600519.SH")
        monkeypatch.setattr(resolver_mod, "infer_code", fake_tool)

        r = await resolve_ticker_full("600519")
        codes = [c.windCode for c in r.resolved]
        assert codes == ["600519.SH"]
        # 纯数字代码不应调用 LLM
        fake_tool.invoke.assert_not_called()

    async def test_llm_answer_already_in_primary_uses_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 推断的 windCode 已在 primary 结果里 → 直接用该候选，无需二次搜索。"""
        searches: list[str] = []

        client = MagicMock()

        async def _search(req):
            kw = req.keywordItems[0].keyword if req.keywordItems else ""
            searches.append(kw)
            return {
                "腾讯": [
                    _r("00700.HK", "腾讯控股"),
                    _r("700.O", "TME"),
                ],
            }.get(kw, [])

        client.search_securities_instrument = AsyncMock(side_effect=_search)
        monkeypatch.setattr(tools_mod, "_make_client", lambda: client)
        monkeypatch.setattr(resolver_mod, "_make_client", lambda: client)
        _mock_infer_code(monkeypatch, {"腾讯": "00700.HK"})

        r = await resolve_ticker_full("腾讯")
        codes = [c.windCode for c in r.resolved]
        assert "00700.HK" in codes
        # 主搜索 + 不应再搜 "00700.HK"（已在主结果里）
        assert "00700.HK" not in searches, (
            f"LLM 答案已在 primary，不应做二次搜索；实际 searches={searches}"
        )

    async def test_llm_answer_no_goats_match_falls_back_to_primary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 给出 GOATS 找不到的 code → 二次校验失败 → 回退用 primary 结果。"""
        _mock_client(
            monkeypatch,
            {
                "茅台": [_r("600519.SH", "贵州茅台")],
                "999999.XX": [],  # LLM 瞎编 → GOATS 找不到
            },
        )
        _mock_infer_code(monkeypatch, {"茅台": "999999.XX"})

        r = await resolve_ticker_full("茅台")
        codes = [c.windCode for c in r.resolved]
        # LLM 答案校验失败 → 仍用 primary 的 600519.SH
        assert codes == ["600519.SH"], f"应回退 primary，实际 {codes}"
