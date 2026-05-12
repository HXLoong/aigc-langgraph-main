"""option.extract_cancel + extract_confirm + extract_query 节点测试（mock LLM）。

3 个节点共用 schema（OrderRefList）但语义不同。合并到一份测试文件。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import (
    extract_cancel as cancel_module,
)
from app.subgraphs.option import (
    extract_confirm as confirm_module,
)
from app.subgraphs.option import (
    extract_query as query_module,
)
from app.subgraphs.option.extract_cancel import (
    _expected_action as cancel_action,
)
from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.extract_confirm import (
    _expected_action as confirm_action,
)
from app.subgraphs.option.extract_confirm import option_extract_confirm
from app.subgraphs.option.extract_query import option_extract_query
from app.subgraphs.option.models import (
    OptionExtractCancelParams,
    OptionExtractConfirmParams,
    OptionExtractQueryParams,
    OptionOrderRefItem,
)


def _patch(
    monkeypatch: pytest.MonkeyPatch, module: object, value: object
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, "get_qwen_thinking", lambda: fake_base)
    return fake_llm.ainvoke


# ============================================================
# expected_action 推导
# ============================================================


class TestCancelExpectedAction:
    def test_cancel_order_request(self) -> None:
        assert cancel_action("cancel_order_request") == "cancel_request"

    def test_request_cancel_order(self) -> None:
        assert cancel_action("request_cancel_order") == "request_cancel"

    def test_unknown_falls_back(self) -> None:
        assert cancel_action(None) == "cancel_request"
        assert cancel_action("garbage") == "cancel_request"


class TestConfirmExpectedAction:
    def test_confirm_order(self) -> None:
        assert confirm_action("confirm_order") == "place"

    def test_confirm_cancel(self) -> None:
        assert confirm_action("confirm_cancel_order") == "cancel"

    def test_confirm_modify(self) -> None:
        assert confirm_action("confirm_modify_order") == "modify"

    def test_unknown_falls_back_to_place(self) -> None:
        assert confirm_action(None) == "place"


# ============================================================
# extract_cancel 节点
# ============================================================


@pytest.mark.asyncio
class TestExtractCancelNode:
    async def test_cancel_with_q_orderid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractCancelParams(
            orderList=[OptionOrderRefItem(orderId="Q-20250616-000017")]
        )
        _patch(monkeypatch, cancel_module, params)
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

    async def test_cancel_request_intent_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractCancelParams(
            orderList=[OptionOrderRefItem(orderId="Q-1")]
        )
        _patch(monkeypatch, cancel_module, params)
        result = await option_extract_cancel(
            {
                "raw_text": "算了不下了",
                "intent": "cancel_order_request",
            }
        )
        assert result["cancel_params"]["expected_action"] == "cancel_request"

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
            {"raw_text": "x", "intent": "cancel_order_request"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_cancel"


# ============================================================
# extract_confirm 节点
# ============================================================


@pytest.mark.asyncio
class TestExtractConfirmNode:
    async def test_confirm_order_maps_action_place(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractConfirmParams(
            orderList=[OptionOrderRefItem(orderId="Q-20250616-000017")]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await option_extract_confirm(
            {
                "raw_text": "确认下单",
                "intent": "confirm_order",
            }
        )
        assert result["confirm"]["action"] == "place"

    async def test_confirm_cancel_maps_action_cancel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractConfirmParams(
            orderList=[OptionOrderRefItem(orderId="Q-1")]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await option_extract_confirm(
            {
                "raw_text": "确认撤单",
                "intent": "confirm_cancel_order",
            }
        )
        assert result["confirm"]["action"] == "cancel"

    async def test_confirm_modify_maps_action_modify(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractConfirmParams(
            orderList=[OptionOrderRefItem(orderId="Q-1")]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await option_extract_confirm(
            {
                "raw_text": "确认改单",
                "intent": "confirm_modify_order",
            }
        )
        assert result["confirm"]["action"] == "modify"

    async def test_multi_orders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractConfirmParams(
            orderList=[
                OptionOrderRefItem(orderId="Q-A"),
                OptionOrderRefItem(orderId="Q-B"),
            ]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await option_extract_confirm(
            {
                "raw_text": "都确认",
                "intent": "confirm_order",
            }
        )
        assert len(result["confirm"]["orderList"]) == 2


# ============================================================
# extract_query 节点
# ============================================================


@pytest.mark.asyncio
class TestExtractQueryNode:
    async def test_query_extracts_orders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractQueryParams(
            orderList=[OptionOrderRefItem(orderId="Q-20250616-000017")]
        )
        _patch(monkeypatch, query_module, params)
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
        _patch(monkeypatch, query_module, OptionExtractQueryParams())
        result = await option_extract_query(
            {"raw_text": "查询订单", "intent": "query_order_status"}
        )
        assert result["query_filter"]["orderList"] == []

    async def test_writes_trace_with_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionExtractQueryParams(
            orderList=[
                OptionOrderRefItem(orderId="Q-A"),
                OptionOrderRefItem(orderId="Q-B"),
            ]
        )
        _patch(monkeypatch, query_module, params)
        result = await option_extract_query(
            {"raw_text": "查 Q-A Q-B 状态", "intent": "query_order_status"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_query"
        assert "orders=2" in trace[0].decision
