"""swap.place_order 节点测试（P0 核心，最大节点）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.graph.state import TickerCandidate
from app.subgraphs.swap import place_order as po_module
from app.subgraphs.swap.models import (
    SwapOrderItem,
    SwapPlaceOrderParams,
)
from app.subgraphs.swap.place_order import (
    _expected_action,
    swap_place_order,
)
from app.subgraphs.ticker.resolver import TickerResolution


def _patch_resolver(
    monkeypatch: pytest.MonkeyPatch,
    candidates: list[TickerCandidate],
) -> None:
    resolution = TickerResolution(resolved=candidates, hitl_pending=[])
    monkeypatch.setattr(po_module, "resolve_ticker_full", AsyncMock(return_value=resolution))


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: SwapPlaceOrderParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(po_module, "get_qwen_complex", lambda: fake_base)
    return fake_llm.ainvoke


# ============================================================
# SwapOrderItem 模型
# ============================================================


class TestSwapOrderItem:
    def test_minimal_all_none(self) -> None:
        item = SwapOrderItem()
        assert item.orderId is None
        assert item.placeOrderWindCode is None

    def test_full_buy_order(self) -> None:
        item = SwapOrderItem(
            placeOrderWindCode="0700.HK",
            placeOrderTransactionType="HK_STOCK",
            placeOrderQuantity=1000,
            placeOrderOrderDirection="BUY",
            placeOrderPriceType="LimitOrder",
            placeOrderAlgorithmType="POV",
            placeOrderPrice=320,
            placeOrderPovPercent=25,
            placeOrderShortname="ACCOUNT_L",
        )
        assert item.placeOrderTransactionType == "HK_STOCK"
        assert item.placeOrderOrderDirection == "BUY"
        assert item.placeOrderAlgorithmType == "POV"

    def test_modify_order_with_order_id(self) -> None:
        item = SwapOrderItem(
            orderId="H-20260304-0001",
            placeOrderPrice=350,
        )
        assert item.orderId == "H-20260304-0001"

    @pytest.mark.parametrize(
        "tx_type",
        ["A_SHARE", "HK_STOCK", "US_STOCK", "FUTURES",
         "FUND", "INDEX", "BOND", "OTHERS"],
    )
    def test_all_transaction_types(self, tx_type: str) -> None:
        item = SwapOrderItem(placeOrderTransactionType=tx_type)  # type: ignore[arg-type]
        assert item.placeOrderTransactionType == tx_type

    def test_invalid_direction_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderOrderDirection="HOLD")  # type: ignore[arg-type]

    def test_invalid_price_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SwapOrderItem(placeOrderPriceType="StopLoss")  # type: ignore[arg-type]

    def test_extra_fields_ignored(self) -> None:
        """extra='ignore' 让 LLM 输出多字段不触发 ValidationError。"""
        item = SwapOrderItem.model_validate(
            {"orderId": None, "garbage_field": "x"}
        )
        assert item.orderId is None
        # garbage_field 被丢弃


# ============================================================
# SwapPlaceOrderParams 容器
# ============================================================


class TestSwapPlaceOrderParams:
    def test_default_empty_list(self) -> None:
        p = SwapPlaceOrderParams()
        assert p.orderList == []

    def test_accepts_top_level_type_field(self) -> None:
        """LLM 输出的顶层 'type' 字段被 ignore。"""
        p = SwapPlaceOrderParams.model_validate(
            {"type": "place_order_request", "orderList": []}
        )
        assert p.orderList == []
        # type 字段被丢弃，不在 model 上


# ============================================================
# _expected_action 推导
# ============================================================


class TestExpectedActionDerivation:
    def test_no_orders_defaults_to_place(self) -> None:
        params = SwapPlaceOrderParams()
        assert _expected_action(params) == "place"

    def test_all_null_order_ids_means_place(self) -> None:
        params = SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(placeOrderWindCode="0700.HK"),
                SwapOrderItem(placeOrderWindCode="00005.HK"),
            ]
        )
        assert _expected_action(params) == "place"

    def test_any_order_id_means_modify(self) -> None:
        params = SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(),
                SwapOrderItem(orderId="H-20260304-0001"),
            ]
        )
        assert _expected_action(params) == "modify"


# ============================================================
# 节点端到端（mock LLM + ticker resolver 集成）
# ============================================================


@pytest.mark.asyncio
class TestSwapPlaceOrderNode:
    async def test_place_with_known_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolver 命中标的 → resolver 写 state['tickers']。"""
        _patch_resolver(monkeypatch, [
            TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True),
        ])
        params = SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(
                    placeOrderWindCode="腾讯",
                    placeOrderQuantity=1000,
                    placeOrderOrderDirection="BUY",
                    placeOrderPriceType="LimitOrder",
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await swap_place_order(
            {"raw_text": "互换下单 腾讯 1000 股 限价"}
        )

        assert result["place_params"]["expected_action"] == "place"
        assert result["place_params"]["orderList"][0]["placeOrderQuantity"] == 1000
        tickers = result.get("tickers", [])
        assert any("700" in t.windCode and t.windCode.endswith(".HK") for t in tickers)
        assert all(t.from_goats for t in tickers)

    async def test_modify_when_order_id_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """orderId 非空 → expected_action='modify'（ADR 0001 D5 共用 schema 约定）。"""
        params = SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(
                    orderId="H-20260304-0001",
                    placeOrderPrice=350,
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await swap_place_order({"raw_text": "改 H-20260304-0001 价格 350"})
        assert result["place_params"]["expected_action"] == "modify"

    async def test_multi_distinct_tickers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """多标的下单 → resolver 返回多条。"""
        _patch_resolver(monkeypatch, [
            TickerCandidate(windCode="600519.SH", insShtDesc="贵州茅台", from_goats=True),
            TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True),
        ])
        params = SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(placeOrderWindCode="贵州茅台"),
                SwapOrderItem(placeOrderWindCode="腾讯"),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await swap_place_order(
            {"raw_text": "互换下单 贵州茅台 腾讯 各 100 股"}
        )
        wind_codes = {t.windCode for t in result["tickers"]}
        assert "600519.SH" in wind_codes
        assert any("700" in wc and wc.endswith(".HK") for wc in wind_codes)

    async def test_writes_trace_with_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_resolver(monkeypatch, [
            TickerCandidate(windCode="00700.HK", insShtDesc="腾讯控股", from_goats=True),
        ])
        params = SwapPlaceOrderParams(
            orderList=[SwapOrderItem(placeOrderWindCode="腾讯")]
        )
        _patch_llm(monkeypatch, params)
        result = await swap_place_order(
            {"raw_text": "互换下单 腾讯 100 股"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        decision = trace[0].decision
        assert "action=place" in decision
        assert "orders=1" in decision
        assert "tickers=1" in decision

    async def test_empty_orders_with_unknown_ticker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 没提取到订单 + 标的不在白名单 → 节点仍正常完成。"""
        _patch_llm(monkeypatch, SwapPlaceOrderParams())
        result = await swap_place_order(
            {"raw_text": "莫名其妙的输入"}
        )
        assert result["place_params"]["orderList"] == []
        assert result["tickers"] == []
        # safe_node 没被触发
        assert "error" not in result or result.get("error") is None

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
            po_module, "get_qwen_complex", lambda: fake_llm
        )
        result = await swap_place_order({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "swap_place_order"
