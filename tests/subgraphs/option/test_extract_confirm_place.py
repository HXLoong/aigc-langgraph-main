"""option.extract_confirm_place 节点测试（Dify DSL v2 新节点，confirm_order，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import extract_confirm_place as ecp_module
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.models import OptionConfirmPlaceParams, OptionOrderItem


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: OptionConfirmPlaceParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(ecp_module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


@pytest.mark.asyncio
class TestOptionExtractConfirmPlaceNode:
    async def test_confirm_order_writes_action_place(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionConfirmPlaceParams(
            orderList=[OptionOrderItem(orderId="Q-20250616-000017")]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单", "intent": "confirm_order"}
        )
        assert result["confirm"]["action"] == "place"
        assert result["confirm"]["orderList"][0]["orderId"] == "Q-20250616-000017"

    async def test_confirm_with_supplementary_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """确认下单同时补参：orderType/limitPrice 等一起提取（非仅 orderId）。"""
        params = OptionConfirmPlaceParams(
            orderList=[
                OptionOrderItem(
                    orderId="Q-1", orderType="限价单", limitPrice=12.0
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单 限价12", "intent": "confirm_order"}
        )
        item = result["confirm"]["orderList"][0]
        assert item["orderType"] == "限价单"
        assert item["limitPrice"] == 12.0

    async def test_multi_orders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        params = OptionConfirmPlaceParams(
            orderList=[
                OptionOrderItem(orderId="Q-A"),
                OptionOrderItem(orderId="Q-B"),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_confirm_place(
            {"raw_text": "都确认下单", "intent": "confirm_order"}
        )
        assert len(result["confirm"]["orderList"]) == 2

    async def test_writes_trace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        params = OptionConfirmPlaceParams(orderList=[OptionOrderItem(orderId="Q-1")])
        _patch_llm(monkeypatch, params)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单", "intent": "confirm_order"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_confirm_place"
        assert "action=place" in trace[0].decision

    async def test_safe_node_catches_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(ecp_module, "get_qwen_thinking", lambda: fake_llm)
        result = await option_extract_confirm_place(
            {"raw_text": "确认下单", "intent": "confirm_order"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_confirm_place"
