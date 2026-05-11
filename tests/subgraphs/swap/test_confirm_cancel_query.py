"""swap.confirm + swap.cancel + swap.query_order 节点测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import (
    cancel as cancel_module,
)
from app.subgraphs.swap import (
    confirm as confirm_module,
)
from app.subgraphs.swap import (
    query_order as query_module,
)
from app.subgraphs.swap.cancel import swap_cancel
from app.subgraphs.swap.confirm import (
    _expected_action as confirm_action,
)
from app.subgraphs.swap.confirm import swap_confirm
from app.subgraphs.swap.models import (
    SwapCancelParams,
    SwapConfirmParams,
    SwapOrderRefItem,
    SwapQueryParams,
)
from app.subgraphs.swap.query_order import swap_query_order


def _patch(
    monkeypatch: pytest.MonkeyPatch, module: object, value: object
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, "get_qwen_structured", lambda: fake_base)
    return fake_llm.ainvoke


# ============================================================
# expected_action 推导（confirm 合并版）
# ============================================================


class TestConfirmExpectedAction:
    def test_confirm_order_maps_place(self) -> None:
        assert confirm_action("confirm_order") == "place"

    def test_confirm_cancel_maps_cancel(self) -> None:
        assert confirm_action("confirm_cancel_order") == "cancel"

    def test_confirm_modify_maps_modify(self) -> None:
        assert confirm_action("confirm_modify_order") == "modify"

    def test_unknown_falls_back_to_place(self) -> None:
        assert confirm_action(None) == "place"
        assert confirm_action("garbage") == "place"


# ============================================================
# swap.confirm 节点（合并版）
# ============================================================


@pytest.mark.asyncio
class TestSwapConfirmNode:
    async def test_confirm_order_action_place(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = SwapConfirmParams(
            orderList=[SwapOrderRefItem(orderId="H-20260304-AAAA")]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await swap_confirm(
            {
                "raw_text": "确认下单",
                "quote_content": "订单 H-20260304-AAAA",
                "intent": "confirm_order",
            }
        )
        assert result["confirm"]["action"] == "place"
        assert (
            result["confirm"]["orderList"][0]["orderId"]
            == "H-20260304-AAAA"
        )

    async def test_confirm_cancel_action_cancel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = SwapConfirmParams(
            orderList=[SwapOrderRefItem(orderId="H-1")]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await swap_confirm(
            {"raw_text": "确认撤单", "intent": "confirm_cancel_order"}
        )
        assert result["confirm"]["action"] == "cancel"

    async def test_confirm_modify_action_modify(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = SwapConfirmParams(
            orderList=[SwapOrderRefItem(orderId="H-1")]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await swap_confirm(
            {"raw_text": "确认改单", "intent": "confirm_modify_order"}
        )
        assert result["confirm"]["action"] == "modify"

    async def test_orderid_can_be_null(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """与 Dify schema 一致，orderId 允许 null（找不到时兜底）。"""
        params = SwapConfirmParams(
            orderList=[SwapOrderRefItem(orderId=None)]
        )
        _patch(monkeypatch, confirm_module, params)
        result = await swap_confirm(
            {"raw_text": "确认", "intent": "confirm_order"}
        )
        assert result["confirm"]["orderList"][0]["orderId"] is None


# ============================================================
# swap.cancel 节点
# ============================================================


@pytest.mark.asyncio
class TestSwapCancelNode:
    async def test_extracts_orderid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = SwapCancelParams(
            orderList=[SwapOrderRefItem(orderId="H-20260304-XYZ")]
        )
        _patch(monkeypatch, cancel_module, params)
        result = await swap_cancel(
            {"raw_text": "撤 H-20260304-XYZ"}
        )
        assert (
            result["cancel_params"]["orderList"][0]["orderId"]
            == "H-20260304-XYZ"
        )

    async def test_orderid_null_when_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = SwapCancelParams(
            orderList=[SwapOrderRefItem(orderId=None)]
        )
        _patch(monkeypatch, cancel_module, params)
        result = await swap_cancel({"raw_text": "取消下单"})
        assert result["cancel_params"]["orderList"][0]["orderId"] is None

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
            cancel_module, "get_qwen_structured", lambda: fake_llm
        )
        result = await swap_cancel({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "swap_cancel"


# ============================================================
# swap.query_order 节点
# ============================================================


@pytest.mark.asyncio
class TestSwapQueryOrderNode:
    async def test_extracts_orderid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = SwapQueryParams(
            orderList=[SwapOrderRefItem(orderId="H-20260304-AAAA")]
        )
        _patch(monkeypatch, query_module, params)
        result = await swap_query_order(
            {"raw_text": "TRS 查 H-20260304-AAAA 状态"}
        )
        assert (
            result["query_filter"]["orderList"][0]["orderId"]
            == "H-20260304-AAAA"
        )

    async def test_writes_trace_with_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = SwapQueryParams(
            orderList=[
                SwapOrderRefItem(orderId="H-A"),
                SwapOrderRefItem(orderId="H-B"),
            ]
        )
        _patch(monkeypatch, query_module, params)
        result = await swap_query_order({"raw_text": "查 H-A H-B 状态"})
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "swap_query_order"
        assert "orders=2" in trace[0].decision
