"""option.extract_place_or_modify 节点测试（P0 核心，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.subgraphs.option import (
    extract_place_or_modify as epm_module,
)
from app.subgraphs.option.extract_place_or_modify import (
    _expected_action_from_intent,
    option_extract_place_or_modify,
)
from app.subgraphs.option.models import (
    OptionOrderItem,
    OptionPlaceOrModifyParams,
)


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: OptionPlaceOrModifyParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(epm_module, "get_qwen_thinking", lambda: fake_base)
    monkeypatch.setattr(
        epm_module,
        "call_option_backend",
        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}),
    )
    return fake_llm.ainvoke


# ============================================================
# OptionOrderItem 模型
# ============================================================


class TestOptionOrderItem:
    def test_minimal_with_only_order_id(self) -> None:
        item = OptionOrderItem(orderId="Q-20250616-000011")
        assert item.orderId == "Q-20250616-000011"
        assert item.orderType is None

    def test_market_order(self) -> None:
        item = OptionOrderItem(
            orderId="Q-1", orderType="市价单"
        )
        assert item.orderType == "市价单"

    def test_pov_with_limit(self) -> None:
        item = OptionOrderItem(
            orderId="Q-1",
            orderType="POV",
            povRatio=25.0,
            limitPrice=9.1,
            notionalAmount="1000000",
        )
        assert item.povRatio == 25.0
        assert item.limitPrice == 9.1

    def test_twap_time_format(self) -> None:
        item = OptionOrderItem(
            orderId="Q-1",
            orderType="TWAP",
            algoStartTime="09:30",
            algoEndTime="14:00",
        )
        assert item.algoStartTime == "09:30"

    def test_invalid_order_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OptionOrderItem(orderId="Q-1", orderType="冰山单")  # type: ignore[arg-type]

    def test_order_id_optional(self) -> None:
        """orderId 可选（qwen-max 经常输出 null）。"""
        item = OptionOrderItem.model_validate({})
        assert item.orderId is None

    def test_extra_fields_ignored(self) -> None:
        params = OptionOrderItem.model_validate(
            {"orderId": "Q-1", "garbage": "x"}
        )
        assert params.orderId == "Q-1"


# ============================================================
# OptionPlaceOrModifyParams 容器
# ============================================================


class TestOptionPlaceOrModifyParams:
    def test_default_empty_list(self) -> None:
        p = OptionPlaceOrModifyParams()
        assert p.orderList == []

    def test_with_multiple_orders(self) -> None:
        p = OptionPlaceOrModifyParams(
            orderList=[
                OptionOrderItem(orderId="Q-A", orderType="市价单"),
                OptionOrderItem(orderId="Q-B", orderType="POV", povRatio=25),
            ]
        )
        assert len(p.orderList) == 2

    def test_extra_fields_ignored(self) -> None:
        params = OptionPlaceOrModifyParams.model_validate(
            {"orderList": [], "garbage": "x"}
        )
        assert params.orderList == []


# ============================================================
# expected_action 推导
# ============================================================


class TestExpectedActionFromIntent:
    def test_modify_intent(self) -> None:
        assert _expected_action_from_intent("request_modify_order") == "modify"

    def test_place_intent(self) -> None:
        assert (
            _expected_action_from_intent("place_order_from_quote") == "place"
        )

    def test_unknown_intent_falls_back_to_place(self) -> None:
        assert _expected_action_from_intent("unknown_intent") == "place"
        assert _expected_action_from_intent(None) == "place"


# ============================================================
# 节点端到端
# ============================================================


@pytest.mark.asyncio
class TestOptionExtractPlaceOrModifyNode:
    async def test_place_order_from_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionPlaceOrModifyParams(
            orderList=[
                OptionOrderItem(
                    orderId="Q-20250616-000011",
                    orderType="市价单",
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place_or_modify(
            {
                "raw_text": "市价下单",
                "quote_content": "Q-20250616-000011",
                "intent": "place_order_from_quote",
            }
        )
        assert result["place_params"]["expected_action"] == "place"
        assert len(result["place_params"]["orderList"]) == 1
        assert (
            result["place_params"]["orderList"][0]["orderId"]
            == "Q-20250616-000011"
        )

    async def test_modify_intent_sets_action_modify(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionPlaceOrModifyParams(
            orderList=[
                OptionOrderItem(
                    orderId="Q-1",
                    limitPrice=10,
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place_or_modify(
            {
                "raw_text": "改限价 10",
                "intent": "request_modify_order",
            }
        )
        assert result["place_params"]["expected_action"] == "modify"

    async def test_pov_with_limit_and_notional(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionPlaceOrModifyParams(
            orderList=[
                OptionOrderItem(
                    orderId="Q-20250905-000016",
                    orderType="POV",
                    limitPrice=9.1,
                    povRatio=25.0,
                    notionalAmount="1000000",
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place_or_modify(
            {
                "raw_text": "100 下单 9.1",
                "intent": "place_order_from_quote",
            }
        )
        item = result["place_params"]["orderList"][0]
        assert item["orderType"] == "POV"
        assert item["povRatio"] == 25.0
        assert item["limitPrice"] == 9.1
        assert item["notionalAmount"] == "1000000"

    async def test_empty_order_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, OptionPlaceOrModifyParams())
        result = await option_extract_place_or_modify(
            {
                "raw_text": "x",
                "intent": "place_order_from_quote",
            }
        )
        assert result["place_params"]["orderList"] == []
        assert result["place_params"]["expected_action"] == "place"

    async def test_writes_trace_with_action_and_types(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionPlaceOrModifyParams(
            orderList=[
                OptionOrderItem(orderId="Q-A", orderType="市价单"),
                OptionOrderItem(orderId="Q-B", orderType="POV", povRatio=20),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place_or_modify(
            {
                "raw_text": "x",
                "intent": "place_order_from_quote",
            }
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        decision = trace[0].decision
        assert "action=place" in decision
        assert "orders=2" in decision

    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(
            epm_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await option_extract_place_or_modify(
            {"raw_text": "x", "intent": "place_order_from_quote"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_place_or_modify"
