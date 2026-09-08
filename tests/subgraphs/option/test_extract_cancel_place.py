"""option.extract_cancel_place 节点测试（Dify DSL v2 新节点，cancel_order_request，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import extract_cancel_place as ecp_module
from app.subgraphs.option.extract_cancel_place import option_extract_cancel_place
from app.subgraphs.option.models import OptionCancelPlaceParams, OptionOrderItem


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: OptionCancelPlaceParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(ecp_module, "get_qwen_thinking", lambda: fake_base)
    monkeypatch.setattr(ecp_module, "call_option_backend",
                        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}))
    return fake_llm.ainvoke


@pytest.mark.asyncio
class TestOptionExtractCancelPlaceNode:
    async def test_cancel_order_request_writes_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionCancelPlaceParams(
            orderList=[OptionOrderItem(orderId="Q-20250616-000017")]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_cancel_place(
            {"raw_text": "算了不下了", "intent": "cancel_order_request"}
        )
        assert result["cancel_params"]["expected_action"] == "cancel_request"
        assert (
            result["cancel_params"]["orderList"][0]["orderId"]
            == "Q-20250616-000017"
        )

    async def test_empty_order_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(monkeypatch, OptionCancelPlaceParams())
        result = await option_extract_cancel_place(
            {"raw_text": "取消下单", "intent": "cancel_order_request"}
        )
        assert result["cancel_params"]["orderList"] == []

    async def test_writes_trace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        params = OptionCancelPlaceParams(orderList=[OptionOrderItem(orderId="Q-1")])
        _patch_llm(monkeypatch, params)
        result = await option_extract_cancel_place(
            {"raw_text": "取消下单", "intent": "cancel_order_request"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_cancel_place"
        assert "cancel_request" in trace[0].decision

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
        result = await option_extract_cancel_place(
            {"raw_text": "取消下单", "intent": "cancel_order_request"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_cancel_place"
