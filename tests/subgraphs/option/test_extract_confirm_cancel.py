"""option.extract_confirm_cancel 节点测试（Dify DSL v2 新节点，confirm_cancel_order，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import extract_confirm_cancel as ecc_module
from app.subgraphs.option.extract_confirm_cancel import option_extract_confirm_cancel
from app.subgraphs.option.models import OptionConfirmCancelParams, OptionOrderItem


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: OptionConfirmCancelParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(ecc_module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


@pytest.mark.asyncio
class TestOptionExtractConfirmCancelNode:
    async def test_confirm_cancel_order_writes_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionConfirmCancelParams(
            orderList=[OptionOrderItem(orderId="Q-20250903-000027")]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_confirm_cancel(
            {"raw_text": "确认撤单", "intent": "confirm_cancel_order"}
        )
        assert result["confirm"]["action"] == "cancel"
        assert result["confirm"]["orderList"][0]["orderId"] == "Q-20250903-000027"

    async def test_multi_orders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        params = OptionConfirmCancelParams(
            orderList=[
                OptionOrderItem(orderId="Q-A"),
                OptionOrderItem(orderId="Q-B"),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_confirm_cancel(
            {"raw_text": "确认撤单", "intent": "confirm_cancel_order"}
        )
        assert len(result["confirm"]["orderList"]) == 2

    async def test_writes_trace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        params = OptionConfirmCancelParams(orderList=[OptionOrderItem(orderId="Q-1")])
        _patch_llm(monkeypatch, params)
        result = await option_extract_confirm_cancel(
            {"raw_text": "确认撤单", "intent": "confirm_cancel_order"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_confirm_cancel"
        assert "action=cancel" in trace[0].decision

    async def test_safe_node_catches_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(ecc_module, "get_qwen_thinking", lambda: fake_llm)
        result = await option_extract_confirm_cancel(
            {"raw_text": "确认撤单", "intent": "confirm_cancel_order"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_confirm_cancel"
