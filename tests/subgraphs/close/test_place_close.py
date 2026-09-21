"""close.place_close 节点测试（P0 核心，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.models import (
    CloseOrderItem,
    ClosePlaceParams,
)
from app.subgraphs.close.place_close import close_place_close
from tests.subgraphs.close.candidate_fixtures import close_candidates


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: BaseModel
) -> AsyncMock:
    monkeypatch.setattr(pc_module, "_fetch_order_data", AsyncMock(return_value=[]))
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
        assert item.order_id is None
        assert item.close_order_type is None
        assert item.confirm_full_close is None

    def test_market_order(self) -> None:
        item = CloseOrderItem(
            orderId="CO-20260304-AAAA0001",
            closeOrderNotionalDelta="2000000",
            closeOrderType="市价单",
        )
        assert item.close_order_type == "市价单"

    def test_limit_order_with_price(self) -> None:
        item = CloseOrderItem(
            orderId="CO-20260304-AAAA0001",
            closeOrderType="限价单",
            closeOrderPrice=10.5,
        )
        assert item.close_order_price == 10.5

    def test_pov_order_with_ratio(self) -> None:
        item = CloseOrderItem(
            orderId="CO-1",
            closeOrderType="POV",
            closeOrderPovRatio=25,
        )
        assert item.close_order_pov_ratio == 25

    def test_twap_order_with_time_range(self) -> None:
        item = CloseOrderItem(
            orderId="CO-1",
            closeOrderType="TWAP",
            closeOrderAlgoStartTime="13:00",
            closeOrderAlgoEndTime="14:00",
        )
        assert item.close_order_algo_start_time == "13:00"

    def test_full_close_confirmation(self) -> None:
        item = CloseOrderItem(orderId="CO-1", confirmFullClose=True)
        assert item.confirm_full_close is True

    def test_invalid_close_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CloseOrderItem(closeOrderType="冰山单")  # type: ignore[arg-type]

    def test_extra_field_ignored(self) -> None:
        item = CloseOrderItem.model_validate(
            {"orderId": "CO-1", "garbage": "x"}
        )
        assert item.order_id == "CO-1"


# ============================================================
# ClosePlaceParams 容器
# ============================================================


class TestClosePlaceParams:
    def test_default_empty_list(self) -> None:
        p = ClosePlaceParams()
        assert p.close_order_list == []

    def test_with_multiple_orders(self) -> None:
        p = ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(orderId="CO-A", closeOrderType="市价单"),
                CloseOrderItem(orderId="CO-B", closeOrderType="限价单",
                               closeOrderPrice=10),
            ]
        )
        assert len(p.close_order_list) == 2

    def test_extra_field_ignored(self) -> None:
        params = ClosePlaceParams.model_validate(
            {"closeOrderList": [], "garbage": "x"}
        )
        assert params.close_order_list == []


# ============================================================
# 节点端到端（mock LLM）
# ============================================================


@pytest.mark.asyncio
class TestClosePlaceCloseNode:
    async def test_single_market_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(monkeypatch, close_candidates({"orderId": "CO-20260304-AAAA0001",
                   "closeOrderNotionalDelta": "200万", "closeOrderType": "市价"}))
        result = await close_place_close({"raw_text": "平 CO-20260304-AAAA0001 200万 市价"})
        assert len(result["close_params"]["closeOrderList"]) == 1
        assert result["close_params"]["closeOrderList"][0]["closeOrderType"] == "市价单"

    async def test_empty_close_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(monkeypatch, close_candidates())
        result = await close_place_close({"raw_text": "x"})
        assert result["close_params"]["closeOrderList"] == []
        assert result.get("error") is None
        assert result["reply_text"] == "未能识别平仓参数，请提供订单号或持仓序号。"

    async def test_full_close_confirmation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(monkeypatch, close_candidates({"orderId": "CO-20260304-AAAA0001",
                                                  "confirmFullClose": "全部平仓"}))
        result = await close_place_close({"raw_text": "CO-20260304-AAAA0001 全部平仓"})
        assert result["close_params"]["closeOrderList"][0]["confirmFullClose"] is True

    async def test_writes_trace_with_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(monkeypatch, close_candidates(
            {"internalTradeId": "OPT-A", "closeOrderType": "市价"},
            {"internalTradeId": "OPT-B", "closeOrderType": "限价", "closeOrderPrice": "10"},
            {"internalTradeId": "OPT-C", "confirmFullClose": "全平"}))
        result = await close_place_close({"raw_text": "OPT-A 市价，OPT-B 限价10，OPT-C 全平"})
        summary = [e for e in result.get("trace", []) if e.node == "close_place_close"]
        assert len(summary) == 1
        assert "orders=3" in summary[0].decision
        assert "市价单" in summary[0].decision
        assert "full_close=1" in summary[0].decision

    async def test_passes_raw_and_quote_to_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ainvoke = _patch_llm(monkeypatch, close_candidates())
        await close_place_close({"raw_text": "第一笔限价 10", "quote_content": "1. CO-20260304-AAAA"})
        user_content = ainvoke.call_args[0][0][-1][1]
        assert "User input: 第一笔限价 10" in user_content
        assert "quote_content：1. CO-20260304-AAAA" in user_content

    async def test_safe_node_catches_llm_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ainvoke = _patch_llm(monkeypatch, close_candidates())
        ainvoke.side_effect = RuntimeError("LLM down")
        result = await close_place_close({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "place_close_extract"
