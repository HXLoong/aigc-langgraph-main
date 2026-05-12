"""option.extract_inquiry 节点测试 · 含 ticker resolver 集成验证。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.subgraphs.option import extract_inquiry as ei_module
from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from app.subgraphs.option.models import (
    OptionInquiryItem,
    OptionInquiryParams,
)


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: OptionInquiryParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(ei_module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


# ============================================================
# OptionInquiryItem 模型
# ============================================================


class TestOptionInquiryItem:
    def test_minimal_all_none(self) -> None:
        item = OptionInquiryItem()
        assert item.stockCode is None
        assert item.optionType is None

    def test_full_item(self) -> None:
        item = OptionInquiryItem(
            stockCode="腾讯控股",
            optionType="欧式看涨",
            tenor="1M",
            strikePercentage=100.0,
            notionalAmount=10000000,
            participationRate=None,
        )
        assert item.optionType == "欧式看涨"

    def test_invalid_option_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OptionInquiryItem(optionType="美式看涨")  # type: ignore[arg-type]

    def test_extra_fields_ignored(self) -> None:
        params = OptionInquiryItem.model_validate(
            {"stockCode": "腾讯", "garbage": "x"}
        )
        assert params.stockCode == "腾讯"

    @pytest.mark.parametrize(
        "valid_type",
        ["欧式看涨", "欧式看跌", "雪球", "气囊", "参与型看涨"],
    )
    def test_all_valid_option_types(self, valid_type: str) -> None:
        item = OptionInquiryItem(optionType=valid_type)  # type: ignore[arg-type]
        assert item.optionType == valid_type


# ============================================================
# 节点端到端
# ============================================================


@pytest.mark.asyncio
class TestOptionExtractInquiryNode:
    async def test_inquiry_with_known_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """白名单内的标的（"腾讯"）→ resolver 写 state['tickers']。"""
        params = OptionInquiryParams(
            orderList=[
                OptionInquiryItem(
                    stockCode="腾讯",
                    optionType="欧式看涨",
                    tenor="1M",
                    strikePercentage=100.0,
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_inquiry(
            {"raw_text": "期权询价 腾讯 欧式看涨 行权价100% 1个月"}
        )

        # LLM 提取的参数
        assert result["place_params"]["expected_action"] == "inquiry"
        assert (
            result["place_params"]["orderList"][0]["stockCode"] == "腾讯"
        )

        # ticker resolver 集成：react 模式下"腾讯"应被识别为港股腾讯控股（0700.HK 或 00700.HK）
        tickers = result.get("tickers", [])
        assert len(tickers) >= 1
        wind_codes = [t.windCode for t in tickers]
        assert any("700" in wc and wc.endswith(".HK") for wc in wind_codes)
        # CLAUDE.md 硬约束：所有 ticker 必须 from_goats=True
        assert all(t.from_goats for t in tickers)

    async def test_inquiry_with_unknown_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """节点正常完成，LLM 提取不受 ticker resolver 影响。"""
        params = OptionInquiryParams(
            orderList=[
                OptionInquiryItem(stockCode="某不存在的标的", tenor="1M")
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_inquiry(
            {"raw_text": "询价 某不存在的标的 1M"}
        )
        # 真实 API 可能模糊匹配到结果，不强制要求空
        assert isinstance(result.get("tickers"), list)
        # LLM 提取仍然返回（resolver 结果不影响 LLM 结果）
        assert (
            result["place_params"]["orderList"][0]["stockCode"]
            == "某不存在的标的"
        )

    async def test_inquiry_multi_distinct_tickers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """用户原话含多个白名单标的 → resolver 返回多条。"""
        import app.subgraphs.ticker.resolver as _resolver
        monkeypatch.setattr(_resolver, "DEFAULT_MODE", "whitelist")
        params = OptionInquiryParams(
            orderList=[
                OptionInquiryItem(stockCode="茅台", optionType="雪球"),
                OptionInquiryItem(stockCode="腾讯", optionType="雪球"),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_inquiry(
            {"raw_text": "雪球询价 茅台 和 腾讯 1Y"}
        )
        wind_codes = {t.windCode for t in result["tickers"]}
        assert "600519.SH" in wind_codes
        assert "00700.HK" in wind_codes

    async def test_writes_trace_with_ticker_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionInquiryParams(
            orderList=[
                OptionInquiryItem(stockCode="腾讯", optionType="雪球"),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_inquiry(
            {"raw_text": "雪球询价 腾讯"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        decision = trace[0].decision
        assert "action=inquiry" in decision
        assert "orders=1" in decision
        assert "tickers=1" in decision

    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(
            ei_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await option_extract_inquiry({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_inquiry"
