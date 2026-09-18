"""swap confirm / cancel / query_order 节点测试(瘦身 P1 去 LLM 化后)。

三节点不再调 LLM,订单号由 app/subgraphs/swap/order_id.py 确定性提取
(提取器细粒度行为见 test_order_id.py,本文件测节点装配:state 输出形状、
二次校验、backend 载荷、safe_node 兜底)。
"""
from __future__ import annotations

import pytest

import app.subgraphs.swap.cancel as cancel_module
import app.subgraphs.swap.confirm as confirm_module
import app.subgraphs.swap.query_order as query_module
from app.subgraphs.swap.cancel import swap_cancel
from app.subgraphs.swap.confirm import (
    _expected_action,
    confirm_order_secondary_check_passed,
    swap_confirm,
)
from app.subgraphs.swap.query_order import swap_query_order

ORDER = "H-20260304-0000000001"
ORDER2 = "H-20260304-0000000002"


def _patch_backend(monkeypatch: pytest.MonkeyPatch, module: object) -> list[dict]:
    """打桩 call_swap_backend,记录调用载荷。"""
    calls: list[dict] = []

    async def fake_backend(state, *, intent, order_list):
        calls.append({"intent": intent, "order_list": order_list})
        return {"api_result": "mock", "api_code": 0}

    monkeypatch.setattr(module, "call_swap_backend", fake_backend)
    return calls


class TestConfirmExpectedAction:
    def test_confirm_order_maps_place(self) -> None:
        assert _expected_action("confirm_order") == "place"

    def test_confirm_cancel_maps_cancel(self) -> None:
        assert _expected_action("confirm_cancel_order") == "cancel"

    def test_confirm_modify_maps_modify(self) -> None:
        assert _expected_action("confirm_modify_order") == "modify"

    def test_unknown_falls_back_to_place(self) -> None:
        assert _expected_action(None) == "place"


class TestConfirmOrderSecondaryCheck:
    @pytest.mark.parametrize("raw_text", ["确认下单", " 确认下单 ", "序号2，确认下单", "序号4、序号2，确认下单"])
    def test_passes_with_keyword(self, raw_text: str) -> None:
        assert confirm_order_secondary_check_passed(raw_text)

    @pytest.mark.parametrize("raw_text", ["确认", "下单", "好的", "", None, "swap确定下单", "确认订单 H-1", "下单确认!"])
    def test_fails_without_keyword(self, raw_text: str | None) -> None:
        assert not confirm_order_secondary_check_passed(raw_text)


class TestSwapConfirmNode:
    @pytest.mark.asyncio
    async def test_confirm_order_extracts_all_from_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm(
            {
                "intent": "confirm_order",
                "raw_text": "确认下单",
                "quote_content": f"订单{ORDER}(序号1)\n订单{ORDER2}(序号2)",
            }
        )
        assert out["confirm"]["action"] == "place"
        assert out["expected_action"] == "place"
        ids = [o["orderId"] for o in out["confirm"]["orderList"]]
        assert ids == [ORDER, ORDER2]
        assert calls[0]["intent"] == "confirm_order"

    @pytest.mark.asyncio
    async def test_confirm_cancel_action_cancel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm(
            {
                "intent": "confirm_cancel_order",
                "raw_text": "确认撤单",
                "quote_content": f"单号:{ORDER}",
            }
        )
        assert out["confirm"]["action"] == "cancel"
        assert out["expected_action"] == "cancel"
        assert out["confirm"]["orderList"][0]["orderId"] == ORDER
        assert calls[0]["intent"] == "confirm_cancel_order"

    @pytest.mark.asyncio
    async def test_confirm_modify_action_modify(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm(
            {
                "intent": "confirm_modify_order",
                "raw_text": "确认改单",
                "quote_content": f"单号:{ORDER}",
            }
        )
        assert out["confirm"]["action"] == "modify"
        assert out["expected_action"] == "modify"

    @pytest.mark.asyncio
    async def test_bare_confirm_requires_quote_despite_conversation_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CWAIJY-957：互换确认下单必须引用，记忆不能扩大用户授权范围。"""
        calls = _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm({
            "intent": "confirm_order", "raw_text": "确认下单", "quote_content": "",
            "last_confirmed_params": {"product_type": "swap", "order_ids": [ORDER, ORDER2]},
        })
        assert out["confirm"] is None
        assert calls == []
        assert "请引用" in out["reply_text"]

    @pytest.mark.asyncio
    async def test_explicit_quote_wins_over_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm({
            "intent": "confirm_order", "raw_text": "确认下单", "quote_content": f"单号:{ORDER}",
            "last_confirmed_params": {"product_type": "swap", "order_ids": [ORDER2]},
        })
        assert [o["orderId"] for o in out["confirm"]["orderList"]] == [ORDER]

    @pytest.mark.asyncio
    async def test_memory_of_other_product_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm({
            "intent": "confirm_cancel_order", "raw_text": "确认撤单", "quote_content": "",
            "last_confirmed_params": {"product_type": "option", "order_ids": ["Q-20260917-AB12CD"]},
        })
        assert out["confirm"]["orderList"][0]["orderId"] is None

    @pytest.mark.asyncio
    async def test_orderid_can_be_null(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm(
            {"intent": "confirm_cancel_order", "raw_text": "确认撤单", "quote_content": ""}
        )
        assert out["confirm"]["orderList"][0]["orderId"] is None


class TestSwapConfirmSecondaryCheckNode:
    @pytest.mark.asyncio
    async def test_confirm_order_without_keyword_sets_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm(
            {"intent": "confirm_order", "raw_text": "好的", "quote_content": f"单号:{ORDER}"}
        )
        assert out.get("error") is None
        assert "确认指令格式不正确" in out["reply_text"]
        assert calls == []  # 未过校验绝不调后端

    @pytest.mark.asyncio
    async def test_confirm_cancel_order_bypasses_secondary_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_backend(monkeypatch, confirm_module)
        out = await swap_confirm(
            {
                "intent": "confirm_cancel_order",
                "raw_text": "随便说说",  # 无确认下单关键词也放行(DSL 二次校验仅限 confirm_order)
                "quote_content": f"单号:{ORDER}",
            }
        )
        assert out.get("error") is None
        assert out["confirm"]["action"] == "cancel"


class TestSwapCancelNode:
    @pytest.mark.asyncio
    async def test_raw_explicit_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _patch_backend(monkeypatch, cancel_module)
        out = await swap_cancel(
            {"raw_text": f"撤掉 {ORDER2}", "quote_content": f"单号:{ORDER}"}
        )
        assert out["cancel_params"]["orderList"][0]["orderId"] == ORDER2
        assert calls[0]["intent"] == "cancel_order_request"

    @pytest.mark.asyncio
    async def test_quote_all_when_raw_bare(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_backend(monkeypatch, cancel_module)
        out = await swap_cancel(
            {"raw_text": "全部撤单", "quote_content": f"单号:{ORDER}\n单号:{ORDER2}"}
        )
        ids = [o["orderId"] for o in out["cancel_params"]["orderList"]]
        assert ids == [ORDER, ORDER2]

    @pytest.mark.asyncio
    async def test_orderid_null_when_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_backend(monkeypatch, cancel_module)
        out = await swap_cancel({"raw_text": "撤单", "quote_content": ""})
        assert out["cancel_params"]["orderList"][0]["orderId"] is None

    @pytest.mark.asyncio
    async def test_safe_node_catches_backend_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def boom(state, *, intent, order_list):
            raise RuntimeError("backend boom")

        monkeypatch.setattr(cancel_module, "call_swap_backend", boom)
        out = await swap_cancel({"raw_text": f"撤 {ORDER}"})
        assert out["error"] is not None
        assert out["error"].node == "swap_cancel"


class TestSwapQueryOrderNode:
    @pytest.mark.asyncio
    async def test_raw_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _patch_backend(monkeypatch, query_module)
        out = await swap_query_order(
            {"raw_text": f"查 {ORDER2}", "quote_content": f"单号:{ORDER}"}
        )
        assert out["query_filter"]["orderList"][0]["orderId"] == ORDER2
        assert calls[0]["intent"] == "query_order_status"

    @pytest.mark.asyncio
    async def test_quote_fallback_and_trace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_backend(monkeypatch, query_module)
        out = await swap_query_order(
            {"raw_text": "订单怎么样了", "quote_content": f"单号:{ORDER}"}
        )
        assert out["query_filter"]["orderList"][0]["orderId"] == ORDER
        trace = [e for e in out["trace"] if e.node == "swap_query_order"]
        assert trace and trace[0].decision.startswith("deterministic")
