"""option.extract_inquiry 节点测试 · 含 ticker resolver 集成验证。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.graph.state import TickerCandidate
from app.subgraphs.option import extract_inquiry as ei_module
from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from app.subgraphs.option.models import (
    OptionInquiryParams,
    OptionOrderItem,
)
from app.subgraphs.ticker.resolver import TickerResolution


def _patch_resolver(
    monkeypatch: pytest.MonkeyPatch,
    candidates: list[TickerCandidate],
) -> None:
    """让 resolve_ticker_full 和 resolve_ticker 都返回指定候选，不调真后端。"""
    resolution = TickerResolution(resolved=candidates, hitl_pending=[])
    monkeypatch.setattr(ei_module, "resolve_ticker_full", AsyncMock(return_value=resolution))
    monkeypatch.setattr(ei_module, "resolve_ticker", AsyncMock(return_value=candidates))


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: OptionInquiryParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(ei_module, "get_qwen_thinking", lambda: fake_base)
    monkeypatch.setattr(
        ei_module,
        "call_option_backend",
        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}),
    )
    return fake_llm.ainvoke


# ============================================================
# OptionOrderItem 模型（询价场景用法）
# ============================================================


class TestOptionOrderItemForInquiry:
    def test_minimal_all_none(self) -> None:
        item = OptionOrderItem()
        assert item.stock_code is None
        assert item.option_type is None

    def test_full_item(self) -> None:
        item = OptionOrderItem(
            stockCode="腾讯控股",
            optionType="欧式看涨",
            tenor="1M",
            strikePercentage=100.0,
            notionalAmount="10000000",
            participationRate=None,
        )
        assert item.option_type == "欧式看涨"

    def test_invalid_option_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OptionOrderItem(optionType="美式看涨")  # type: ignore[arg-type]

    def test_removed_option_types_rejected(self) -> None:
        """Dify DSL v2 收窄：不再支持 欧式看跌/气囊。"""
        for removed in ("欧式看跌", "气囊"):
            with pytest.raises(ValidationError):
                OptionOrderItem(optionType=removed)  # type: ignore[arg-type]

    def test_extra_fields_ignored(self) -> None:
        params = OptionOrderItem.model_validate(
            {"stockCode": "腾讯", "garbage": "x"}
        )
        assert params.stock_code == "腾讯"

    @pytest.mark.parametrize(
        "valid_type",
        ["欧式看涨", "雪球", "参与型看涨"],
    )
    def test_all_valid_option_types(self, valid_type: str) -> None:
        item = OptionOrderItem(optionType=valid_type)  # type: ignore[arg-type]
        assert item.option_type == valid_type


# ============================================================
# 节点端到端
# ============================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("codes", [["600519.SH", "AZ.O"], ["AZ.O", "600519.SH"], ["600519.SH"]])
async def test_case_026_backend_orders_keep_their_ticker(monkeypatch, codes) -> None:
    """One instrument can back multiple orders, even with a spurious resolver winner."""
    from app.subgraphs.option.backend import call_option_backend

    _patch_resolver(monkeypatch, [
        TickerCandidate(windCode=code, from_goats=True) for code in codes
    ])
    params = OptionInquiryParams(orderList=[
        OptionOrderItem(stockCode="600519.SH", tenor=tenor, strikePercentage=80.0)
        for tenor in ("1M", "2M")
    ])
    _patch_llm(monkeypatch, params)
    # Exercise request DTO construction too; only the external client is mocked.
    monkeypatch.setattr(ei_module, "call_option_backend", call_option_backend)
    operate = AsyncMock(return_value=MagicMock(code=0, data="inquiry reply"))
    monkeypatch.setattr(
        "app.subgraphs.option.backend.OptionClientHttpx",
        lambda: MagicMock(operate=operate),
    )
    result = await option_extract_inquiry({
        "raw_text": "600519.SH，欧式看涨,1M/2M,80%",
        "conversation_id": "case-026", "message_id": 26,
        "room_id": "test-room", "user_id": "test-user",
    })
    operate.assert_awaited_once()
    orders = operate.call_args.args[0].order_list
    assert [(o.model_dump()["stockCode"], o.tenor, o.model_dump()["strikePercentage"]) for o in orders] == [
        ("600519.SH", "1M", 80.0), ("600519.SH", "2M", 80.0),
    ]
    assert [o["stockCode"] for o in result["place_params"]["orderList"]] == [
        "600519.SH", "600519.SH",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("as_dicts", [False, True])
async def test_inquiry_binds_by_unique_identity_and_preserves_unresolved_values(
    monkeypatch, as_dicts,
) -> None:
    candidates = [
        TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True,
                        sourceKeywords=["腾讯", "shared"]),
        TickerCandidate(windCode="600519.SH", insShtDesc="贵州茅台", insLngDesc="Kweichow Moutai",
                        from_goats=True, sourceKeywords=["茅台", "600519", "shared", "000858.SZ"]),
        TickerCandidate(windCode="AZ.O", from_goats=False, sourceKeywords=["unverified"]),
    ]
    if as_dicts:
        candidates = [ticker.model_dump() for ticker in reversed(candidates)]
    _patch_resolver(monkeypatch, candidates)
    originals = [
        "茅台", "茅台", "腾讯", "腾讯", " 600519 ", "贵州茅台", " kweichow moutai ",
        " 600519.sh ", "unknown", "shared", None, "unverified", "000858.SZ", "茅",
    ]
    params = OptionInquiryParams(orderList=[
        OptionOrderItem(stockCode=stock_code, tenor="1M" if i % 2 == 0 else "2M")
        for i, stock_code in enumerate(originals)
    ])
    _patch_llm(monkeypatch, params)
    result = await option_extract_inquiry({"raw_text": "茅台 腾讯 1M/2M"})
    sent = ei_module.call_option_backend.call_args.kwargs["order_list"]
    expected = [
        "600519.SH", "600519.SH", "00700.HK", "00700.HK", "600519.SH", "600519.SH",
        "600519.SH", "600519.SH", "unknown", "shared", None, "unverified", "000858.SZ", "茅",
    ]
    assert [order["stockCode"] for order in sent] == expected
    assert [order["tenor"] for order in sent] == [item.tenor for item in params.order_list]
    assert [order["stockCode"] for order in result["place_params"]["orderList"]] == originals
    bindings = result["trace"][0].llm_output["ticker_bindings"]
    assert [binding["backend_stock_code"] for binding in bindings] == expected
    assert [binding["original_stock_code"] for binding in bindings] == originals
    assert [binding["result"] for binding in bindings] == [
        "matched_alias", "matched_alias", "matched_alias", "matched_alias", "matched_alias",
        "matched_alias", "matched_alias", "matched_code", "unmatched", "ambiguous", "missing",
        "unmatched", "unmatched", "unmatched",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("stock_code", [None, "unknown"])
async def test_single_candidate_does_not_fill_unrelated_order(monkeypatch, stock_code) -> None:
    _patch_resolver(monkeypatch, [TickerCandidate(windCode="600519.SH", from_goats=True)])
    _patch_llm(monkeypatch, OptionInquiryParams(orderList=[OptionOrderItem(stockCode=stock_code)]))
    await option_extract_inquiry({"raw_text": "询价"})
    assert ei_module.call_option_backend.call_args.kwargs["order_list"][0]["stockCode"] == stock_code


@pytest.mark.asyncio
class TestOptionExtractInquiryNode:
    async def test_invalid_ticker_is_a_handled_business_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """标的未命中是可预期业务结果，不应污染工程错误状态。"""
        _patch_resolver(monkeypatch, [])

        result = await option_extract_inquiry(
            {"raw_text": "600519.SH，欧式看涨,1M，80%"}
        )

        assert result.get("error") is None
        assert "不在标的池内" in result["reply_text"]

    async def test_inquiry_with_known_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolver 命中标的 → resolver 写 state['tickers']。"""
        _patch_resolver(monkeypatch, [
            TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True),
        ])
        params = OptionInquiryParams(
            orderList=[
                OptionOrderItem(
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

        assert result["place_params"]["expected_action"] == "inquiry"
        assert result["place_params"]["orderList"][0]["stockCode"] == "腾讯"
        tickers = result.get("tickers", [])
        assert len(tickers) >= 1
        assert any("700" in t.wind_code and t.wind_code.endswith(".HK") for t in tickers)
        assert all(t.from_goats for t in tickers)

    async def test_inquiry_with_unknown_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """节点正常完成，LLM 提取不受 ticker resolver 影响。"""
        _patch_resolver(monkeypatch, [])
        params = OptionInquiryParams(
            orderList=[
                OptionOrderItem(stockCode="某不存在的标的", tenor="1M")
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
        """用户原话含多个标的 → resolver 返回多条。"""
        from app.graph.state import TickerCandidate
        from app.subgraphs.ticker.resolver import TickerResolution

        monkeypatch.setattr(
            ei_module,
            "resolve_ticker_full",
            AsyncMock(return_value=TickerResolution(
                resolved=[
                    TickerCandidate(windCode="600519.SH", insShtDesc="贵州茅台", from_goats=True),
                    TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True),
                ],
                hitl_pending=[],
            )),
        )
        params = OptionInquiryParams(
            orderList=[
                OptionOrderItem(stockCode="茅台", optionType="雪球"),
                OptionOrderItem(stockCode="腾讯", optionType="雪球"),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_inquiry(
            {"raw_text": "雪球询价 茅台 和 腾讯 1Y"}
        )
        wind_codes = {t.wind_code for t in result["tickers"]}
        assert "600519.SH" in wind_codes
        assert "00700.HK" in wind_codes

    async def test_writes_trace_with_ticker_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_resolver(monkeypatch, [
            TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True),
        ])
        params = OptionInquiryParams(
            orderList=[
                OptionOrderItem(stockCode="腾讯", optionType="雪球"),
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

    async def test_null_literal_participation_rate_sanitized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 偶发把 notionalAmount 吐成字面量字符串 "null" → sanitize 清成 None。"""
        _patch_resolver(monkeypatch, [])
        params = OptionInquiryParams(
            orderList=[OptionOrderItem(stockCode="腾讯", notionalAmount="null")]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_inquiry({"raw_text": "腾讯询价"})
        assert result["place_params"]["orderList"][0]["notionalAmount"] is None

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
