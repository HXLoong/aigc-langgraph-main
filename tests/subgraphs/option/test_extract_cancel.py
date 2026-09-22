"""option.extract_cancel 节点测试（请求撤单，确定性提取，无 LLM）。

去 LLM 化后行为 1:1 对照原提示词规约：raw 指定具体订单则用 raw；
否则从 quote 取全部；均无 → orderId: null（保持单据形状）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option import extract_cancel as cancel_module
from app.subgraphs.option.extract_cancel import option_extract_cancel
from tests.llm_guard import forbid_llm


def _patch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """固定后端边界；LLM 工厂若被调用即报错（去 LLM 化硬约束）。"""
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(cancel_module, "call_option_backend", backend)

    forbid_llm(monkeypatch, cancel_module)
    return backend


@pytest.mark.asyncio
class TestExtractCancelNode:
    async def test_cancel_with_q_orderid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _patch(monkeypatch)
        result = await option_extract_cancel(
            {"raw_text": "撤单 Q-20250616-000017", "intent": "request_cancel_order"}
        )
        assert result["expected_action"] == "cancel"
        assert "expected_action" not in result["cancel_params"]
        assert result["cancel_params"]["orderList"] == [{"orderId": "Q-20250616-000017"}]
        assert backend.await_args.kwargs["order_list"] == [{"orderId": "Q-20250616-000017"}]

    async def test_all_cancel_takes_quote_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel(
            {
                "raw_text": "全部撤单",
                "quote_content": "待撤订单：Q-20250616-000017、Q-20250616-000021",
                "intent": "request_cancel_order",
            }
        )
        assert [item["orderId"] for item in result["cancel_params"]["orderList"]] == [
            "Q-20250616-000017",
            "Q-20250616-000021",
        ]

    async def test_raw_specified_order_wins_over_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel(
            {
                "raw_text": "撤单 Q-20250616-000017",
                "quote_content": "卡片：Q-20250616-000099",
                "intent": "request_cancel_order",
            }
        )
        assert [item["orderId"] for item in result["cancel_params"]["orderList"]] == [
            "Q-20250616-000017"
        ]

    async def test_quote_ids_deduped_in_first_seen_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel(
            {
                "raw_text": "全部撤单",
                "quote_content": (
                    "第一单 Q-20250616-000021，第二单 Q-20250616-000017，"
                    "重复 Q-20250616-000021"
                ),
                "intent": "request_cancel_order",
            }
        )
        assert [item["orderId"] for item in result["cancel_params"]["orderList"]] == [
            "Q-20250616-000021",
            "Q-20250616-000017",
        ]

    async def test_no_order_keeps_null_item_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel(
            {"raw_text": "全部撤单", "intent": "request_cancel_order"}
        )
        assert result["cancel_params"]["orderList"] == [{"orderId": None}]

    async def test_writes_trace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch(monkeypatch)
        result = await option_extract_cancel(
            {"raw_text": "撤单 Q-20250616-000017", "intent": "request_cancel_order"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_cancel"
        assert "deterministic" in trace[0].decision
        assert "request_cancel" in trace[0].decision
