"""option.extract_cancel_place 节点测试（取消下单，确定性提取，无 LLM）。

原提示词规约：仅从 quote_content 提取 Q- 订单号（用户引用确认卡并选择取消）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option import extract_cancel_place as cancel_place_module
from app.subgraphs.option.extract_cancel_place import option_extract_cancel_place
from tests.llm_guard import forbid_llm


def _patch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(cancel_place_module, "call_option_backend", backend)

    forbid_llm(monkeypatch, cancel_place_module)
    return backend


@pytest.mark.asyncio
class TestOptionExtractCancelPlaceNode:
    async def test_quote_card_order_is_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _patch(monkeypatch)
        result = await option_extract_cancel_place(
            {
                "raw_text": "算了不下了",
                "quote_content": "请确认下单 Q-20250616-000017",
                "intent": "cancel_order_request",
            }
        )
        assert result["expected_action"] == "cancel"
        assert "expected_action" not in result["cancel_params"]
        assert result["cancel_params"]["orderList"] == [{"orderId": "Q-20250616-000017"}]
        assert backend.await_args.kwargs["order_list"] == [{"orderId": "Q-20250616-000017"}]

    async def test_quote_multi_orders_kept_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel_place(
            {
                "raw_text": "取消下单",
                "quote_content": "待确认：Q-20250616-000017、Q-20250616-000021",
                "intent": "cancel_order_request",
            }
        )
        assert [item["orderId"] for item in result["cancel_params"]["orderList"]] == [
            "Q-20250616-000017",
            "Q-20250616-000021",
        ]

    async def test_raw_only_does_not_extract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """原提示词规约：订单号只从引用消息取；raw 单独出现 Q- 不提取。"""
        _patch(monkeypatch)
        result = await option_extract_cancel_place(
            {"raw_text": "取消下单 Q-20250616-000017", "intent": "cancel_order_request"}
        )
        assert result["cancel_params"]["orderList"] == [{"orderId": None}]

    async def test_no_quote_keeps_null_item_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel_place(
            {"raw_text": "取消下单", "intent": "cancel_order_request"}
        )
        assert result["cancel_params"]["orderList"] == [{"orderId": None}]

    async def test_writes_trace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel_place(
            {
                "raw_text": "取消下单",
                "quote_content": "请确认下单 Q-20250616-000017",
                "intent": "cancel_order_request",
            }
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_cancel_place"
        assert "deterministic" in trace[0].decision
        assert "cancel_request" in trace[0].decision
