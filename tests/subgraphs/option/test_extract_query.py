"""option.extract_query 节点测试（query_order_status，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import extract_query as query_module
from app.subgraphs.option.extract_query import option_extract_query
from app.subgraphs.option.models import OptionOrderItem, OptionQueryParams


def _patch(monkeypatch: pytest.MonkeyPatch, value: OptionQueryParams) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(query_module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


@pytest.mark.asyncio
class TestExtractQueryNode:
    async def test_query_extracts_orders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionQueryParams(
            orderList=[OptionOrderItem(orderId="Q-20250616-000017")]
        )
        _patch(monkeypatch, params)
        result = await option_extract_query(
            {
                "raw_text": "查 Q-20250616-000017 的状态",
                "intent": "query_order_status",
            }
        )
        assert (
            result["query_filter"]["orderList"][0]["orderId"]
            == "Q-20250616-000017"
        )

    async def test_empty_orders_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch, OptionQueryParams())
        result = await option_extract_query(
            {"raw_text": "查询订单", "intent": "query_order_status"}
        )
        assert result["query_filter"]["orderList"] == []

    async def test_writes_trace_with_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionQueryParams(
            orderList=[
                OptionOrderItem(orderId="Q-A"),
                OptionOrderItem(orderId="Q-B"),
            ]
        )
        _patch(monkeypatch, params)
        result = await option_extract_query(
            {"raw_text": "查 Q-A Q-B 状态", "intent": "query_order_status"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_query"
        assert "orders=2" in trace[0].decision

    async def test_safe_node_catches_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(query_module, "get_qwen_thinking", lambda: fake_llm)
        result = await option_extract_query(
            {"raw_text": "x", "intent": "query_order_status"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_query"
