"""option.extract_query 节点测试（查询订单状态，确定性提取，无 LLM）。

原提示词规约：raw 或 quote 提到具体订单号则提取；否则 null
（下游接口会查询近期所有订单）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option import extract_query as query_module
from app.subgraphs.option.extract_query import option_extract_query
from tests.llm_guard import forbid_llm


def _patch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(query_module, "call_option_backend", backend)

    forbid_llm(monkeypatch, query_module)
    return backend


@pytest.mark.asyncio
class TestExtractQueryNode:
    async def test_query_extracts_raw_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _patch(monkeypatch)
        result = await option_extract_query(
            {
                "raw_text": "查 Q-20250616-000017 的状态",
                "intent": "query_order_status",
            }
        )
        assert result["query_filter"]["orderList"] == [{"orderId": "Q-20250616-000017"}]
        assert backend.await_args.kwargs["order_list"] == [{"orderId": "Q-20250616-000017"}]

    async def test_query_falls_back_to_quote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_query(
            {
                "raw_text": "这个订单什么状态",
                "quote_content": "订单详情：Q-20250616-000017",
                "intent": "query_order_status",
            }
        )
        assert [item["orderId"] for item in result["query_filter"]["orderList"]] == [
            "Q-20250616-000017"
        ]

    async def test_no_order_keeps_null_item_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_query(
            {"raw_text": "查询订单", "intent": "query_order_status"}
        )
        assert result["query_filter"]["orderList"] == [{"orderId": None}]

    async def test_writes_trace_with_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_query(
            {
                "raw_text": "查 Q-20250616-000017 Q-20250616-000021 状态",
                "intent": "query_order_status",
            }
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_query"
        assert "deterministic" in trace[0].decision
        assert "orders=2" in trace[0].decision
