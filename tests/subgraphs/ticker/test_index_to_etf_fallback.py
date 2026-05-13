"""指数代码 → ETF 结构化后备搜索测试。

LLM `infer_code` 对命名指数关键词非确定性：同一 keyword 不同调用可能返回指数代码
（000xxx.SH/399xxx.SZ）或 ETF 代码（159xxx.SZ/5xxxxx.SH）。导致 eval 评分波动。

修复（结构化判定，非硬编码映射）：当 winner 的 windCode 落在指数代码 numeric 范围
（000xxx.SH 或 399xxx.SZ）且 keyword 含中文 → 触发 ETF 后备搜索：
1. 去除常见指数后缀（"指数" / "指"）
2. 拼上 "ETF" 重新查 GOATS
3. 若 GOATS 有结果 → 用 ETF 替代指数代码（场外期权后端只收 ETF 不收指数）

这是**结构化规则**（指数代码 windCode 范围 + 关键词后缀变换），不是
"创业板指 → 159915.SZ" 这种业务清单映射。
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
    def _fake(input_data):  # type: ignore[no-untyped-def]
        kw = input_data.get("keyword", "") if isinstance(input_data, dict) else str(input_data)
        return mapping.get(kw, kw)

    fake_tool = MagicMock()
    fake_tool.invoke = MagicMock(side_effect=_fake)
    monkeypatch.setattr(resolver_mod, "infer_code", fake_tool)


@pytest.mark.asyncio
class TestIndexToETFFallback:
    """LLM 给出指数代码时 → 触发 ETF 后备搜索。"""

    async def test_index_code_falls_back_to_etf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 返回 399006.SZ（创业板指数代码）→ 自动 fallback 到 创业板ETF 搜索 → 用 ETF。"""
        _mock_client(
            monkeypatch,
            {
                "创业板指": [_r("399006.SZ", "创业板指")],
                "创业板ETF": [_r("159915.SZ", "创业板ETF易方达")],
                "100%": [],
                "3M": [],
            },
        )
        _mock_infer_code(monkeypatch, {"创业板指": "399006.SZ"})

        r = await resolve_ticker_full("创业板指 100% 3M")
        codes = [c.windCode for c in r.resolved]
        assert "159915.SZ" in codes, (
            f"指数代码应触发 ETF 后备，实际 resolved={codes}"
        )
        assert codes[0] == "159915.SZ"

    async def test_sse_index_000xxx_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 返回 000016.SH（上证50指数）→ fallback 到 上证50ETF → 用 ETF 510050.SH。"""
        _mock_client(
            monkeypatch,
            {
                "上证50": [_r("000016.SH", "上证50")],
                "上证50ETF": [_r("510050.SH", "上证50ETF华夏")],
                "100%": [],
                "3M": [],
            },
        )
        _mock_infer_code(monkeypatch, {"上证50": "000016.SH"})

        r = await resolve_ticker_full("上证50 100% 3M")
        codes = [c.windCode for c in r.resolved]
        assert "510050.SH" in codes
        assert codes[0] == "510050.SH"

    async def test_non_index_code_no_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """普通股票代码（非 000xxx/399xxx 索引模式）→ 不触发 ETF 后备。"""
        _mock_client(
            monkeypatch,
            {
                "茅台": [_r("600519.SH", "贵州茅台")],
                "茅台ETF": [_r("159928.SZ", "中证消费ETF华泰柏瑞")],  # 无关 ETF
            },
        )
        _mock_infer_code(monkeypatch, {"茅台": "600519.SH"})

        r = await resolve_ticker_full("茅台")
        codes = [c.windCode for c in r.resolved]
        # 600519.SH 不是索引代码，不该被替换成 159928.SZ
        assert codes == ["600519.SH"]

    async def test_etf_fallback_no_match_keeps_index_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ETF 后备搜索返回空 → 保留原指数代码（不丢失任何识别）。"""
        _mock_client(
            monkeypatch,
            {
                "创业板指": [_r("399006.SZ", "创业板指")],
                "创业板ETF": [],  # ETF 搜索无结果
            },
        )
        _mock_infer_code(monkeypatch, {"创业板指": "399006.SZ"})

        r = await resolve_ticker_full("创业板指")
        codes = [c.windCode for c in r.resolved]
        # 保留指数代码，不空白
        assert codes == ["399006.SZ"]
