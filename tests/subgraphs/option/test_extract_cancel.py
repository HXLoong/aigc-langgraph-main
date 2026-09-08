"""option.extract_cancel 节点测试（Dify DSL v2：仅 request_cancel_order，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import extract_cancel as cancel_module
from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.models import OptionCancelParams, OptionOrderItem


def _patch(
    monkeypatch: pytest.MonkeyPatch, params: OptionCancelParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(cancel_module, "get_qwen_thinking", lambda: fake_base)
    monkeypatch.setattr(cancel_module, "call_option_backend",
                        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}))
    return fake_llm.ainvoke


@pytest.mark.asyncio
class TestExtractCancelNode:
    async def test_cancel_with_q_orderid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionCancelParams(
            orderList=[OptionOrderItem(orderId="Q-20250616-000017")]
        )
        _patch(monkeypatch, params)
        result = await option_extract_cancel(
            {
                "raw_text": "撤单 Q-20250616-000017",
                "intent": "request_cancel_order",
            }
        )
        assert result["cancel_params"]["expected_action"] == "request_cancel"
        assert (
            result["cancel_params"]["orderList"][0]["orderId"]
            == "Q-20250616-000017"
        )

    async def test_empty_order_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch, OptionCancelParams())
        result = await option_extract_cancel(
            {"raw_text": "全部撤单", "intent": "request_cancel_order"}
        )
        assert result["cancel_params"]["orderList"] == []

    async def test_writes_trace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        params = OptionCancelParams(orderList=[OptionOrderItem(orderId="Q-1")])
        _patch(monkeypatch, params)
        result = await option_extract_cancel(
            {"raw_text": "撤单 Q-1", "intent": "request_cancel_order"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_cancel"
        assert "request_cancel" in trace[0].decision

    async def test_safe_node_catches_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(
            cancel_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await option_extract_cancel(
            {"raw_text": "x", "intent": "request_cancel_order"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_cancel"
