"""close.place_close 节点测试（P0 核心，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.models import (
    CloseOrderItem,
    ClosePlaceParams,
)
from app.subgraphs.close.place_close import close_place_close


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: ClosePlaceParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(pc_module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


# ============================================================
# CloseOrderItem 模型
# ============================================================


class TestCloseOrderItem:
    def test_all_optional_fields_default_none(self) -> None:
        item = CloseOrderItem()
        assert item.orderId is None
        assert item.closeOrderType is None
        assert item.confirmFullClose is None

    def test_market_order(self) -> None:
        item = CloseOrderItem(
            orderId="CO-20260304-AAAA0001",
            closeOrderNotionalDelta="2000000",
            closeOrderType="市价单",
        )
        assert item.closeOrderType == "市价单"

    def test_limit_order_with_price(self) -> None:
        item = CloseOrderItem(
            orderId="CO-20260304-AAAA0001",
            closeOrderType="限价单",
            closeOrderPrice=10.5,
        )
        assert item.closeOrderPrice == 10.5

    def test_pov_order_with_ratio(self) -> None:
        item = CloseOrderItem(
            orderId="CO-1",
            closeOrderType="POV",
            closeOrderPovRatio=25,
        )
        assert item.closeOrderPovRatio == 25

    def test_twap_order_with_time_range(self) -> None:
        item = CloseOrderItem(
            orderId="CO-1",
            closeOrderType="TWAP",
            closeOrderAlgoStartTime="13:00",
            closeOrderAlgoEndTime="14:00",
        )
        assert item.closeOrderAlgoStartTime == "13:00"

    def test_full_close_confirmation(self) -> None:
        item = CloseOrderItem(orderId="CO-1", confirmFullClose=True)
        assert item.confirmFullClose is True

    def test_invalid_close_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CloseOrderItem(closeOrderType="冰山单")  # type: ignore[arg-type]

    def test_extra_field_ignored(self) -> None:
        item = CloseOrderItem.model_validate(
            {"orderId": "CO-1", "garbage": "x"}
        )
        assert item.orderId == "CO-1"


# ============================================================
# ClosePlaceParams 容器
# ============================================================


class TestClosePlaceParams:
    def test_default_empty_list(self) -> None:
        p = ClosePlaceParams()
        assert p.closeOrderList == []

    def test_with_multiple_orders(self) -> None:
        p = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(orderId="CO-A", closeOrderType="市价单"),
                CloseOrderItem(orderId="CO-B", closeOrderType="限价单",
                               closeOrderPrice=10),
            ]
        )
        assert len(p.closeOrderList) == 2

    def test_extra_field_ignored(self) -> None:
        params = ClosePlaceParams.model_validate(
            {"closeOrderList": [], "garbage": "x"}
        )
        assert params.closeOrderList == []


# ============================================================
# 节点端到端（mock LLM）
# ============================================================


@pytest.mark.asyncio
class TestClosePlaceCloseNode:
    async def test_single_market_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="CO-20260304-AAAA0001",
                    closeOrderNotionalDelta="2000000",
                    closeOrderType="市价单",
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await close_place_close(
            {"raw_text": "平 CO-20260304-AAAA0001 200万 市价"}
        )
        assert len(result["close_params"]["closeOrderList"]) == 1
        assert (
            result["close_params"]["closeOrderList"][0]["closeOrderType"]
            == "市价单"
        )

    async def test_empty_close_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, ClosePlaceParams())
        result = await close_place_close({"raw_text": "x"})
        assert result["close_params"]["closeOrderList"] == []

    async def test_full_close_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="CO-1",
                    confirmFullClose=True,
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await close_place_close({"raw_text": "全部平仓"})
        assert (
            result["close_params"]["closeOrderList"][0]["confirmFullClose"]
            is True
        )

    async def test_writes_trace_with_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(orderId="CO-A", closeOrderType="市价单"),
                CloseOrderItem(orderId="CO-B", closeOrderType="限价单",
                               closeOrderPrice=10),
                CloseOrderItem(orderId="CO-C", confirmFullClose=True),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await close_place_close({"raw_text": "..."})
        trace = result.get("trace", [])
        assert len(trace) == 1
        decision = trace[0].decision
        assert "orders=3" in decision
        assert "市价单" in decision
        assert "full_close=1" in decision

    async def test_passes_raw_and_quote_to_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ainvoke = _patch_llm(monkeypatch, ClosePlaceParams())
        await close_place_close(
            {
                "raw_text": "第一笔限价 10",
                "quote_content": "1. CO-20260304-AAAA",
            }
        )
        messages = ainvoke.call_args[0][0]
        user_content = messages[-1][1]
        assert "用户发送消息：第一笔限价 10" in user_content
        assert "用户引用消息：1. CO-20260304-AAAA" in user_content

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
            pc_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await close_place_close({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "close_place_close"
