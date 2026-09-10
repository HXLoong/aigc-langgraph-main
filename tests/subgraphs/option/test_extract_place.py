"""option.extract_place 节点测试（Dify DSL v2 新节点，place_order_from_quote，mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.subgraphs.option import extract_place as ep_module
from app.subgraphs.option.extract_place import option_extract_place
from app.subgraphs.option.models import (
    OptionOrderItem,
    OptionOrderItemWithFastExec,
    OptionPlaceParams,
)


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, params: OptionPlaceParams
) -> AsyncMock:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(ep_module, "get_qwen_thinking", lambda: fake_base)
    monkeypatch.setattr(ep_module, "call_option_backend",
                        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}))
    return fake_llm.ainvoke


# ============================================================
# OptionPlaceParams 容器
# ============================================================


class TestOptionPlaceParams:
    def test_default_empty_list(self) -> None:
        p = OptionPlaceParams()
        assert p.order_list == []

    def test_with_multiple_orders(self) -> None:
        p = OptionPlaceParams(
            orderList=[
                OptionOrderItemWithFastExec(orderId="Q-A", orderType="市价单"),
                OptionOrderItemWithFastExec(orderId="Q-B", orderType="POV", povRatio=25),
            ]
        )
        assert len(p.order_list) == 2

    def test_plain_dict_defaults_fast_exec_to_none(self) -> None:
        """orderList item 类型是 OptionOrderItemWithFastExec，普通 dict 仍可校验通过。"""
        p = OptionPlaceParams.model_validate({"orderList": [{"orderId": "Q-1"}]})
        assert p.order_list[0].has_fast_execution_intent is None

    def test_invalid_order_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OptionPlaceParams(
                orderList=[OptionOrderItem(orderId="Q-1", orderType="冰山单")]  # type: ignore[arg-type]
            )


# ============================================================
# 节点端到端
# ============================================================


@pytest.mark.asyncio
class TestOptionExtractPlaceNode:
    async def test_place_order_from_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionPlaceParams(
            orderList=[
                OptionOrderItemWithFastExec(
                    orderId="Q-20250616-000011",
                    orderType="市价单",
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place(
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

    async def test_pov_with_limit_and_notional(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionPlaceParams(
            orderList=[
                OptionOrderItemWithFastExec(
                    orderId="Q-20250905-000016",
                    orderType="POV",
                    limitPrice=9.1,
                    povRatio=25.0,
                    notionalAmount="1000000",
                )
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place(
            {"raw_text": "100W下单9.1", "intent": "place_order_from_quote"}
        )
        item = result["place_params"]["orderList"][0]
        assert item["orderType"] == "POV"
        assert item["povRatio"] == 25.0
        assert item["limitPrice"] == 9.1
        assert item["notionalAmount"] == "1000000"

    async def test_null_literal_shortname_sanitized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 偶发吐出字面量字符串 "null" → 节点内 sanitize 清成 None。"""
        params = OptionPlaceParams(
            orderList=[OptionOrderItemWithFastExec(orderId="Q-1", shortName="null")]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place(
            {"raw_text": "x", "intent": "place_order_from_quote"}
        )
        assert result["place_params"]["orderList"][0]["shortName"] is None

    async def test_empty_order_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_llm(monkeypatch, OptionPlaceParams())
        result = await option_extract_place(
            {"raw_text": "x", "intent": "place_order_from_quote"}
        )
        assert result["place_params"]["orderList"] == []
        assert result["place_params"]["expected_action"] == "place"

    async def test_writes_trace_with_action_and_types(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        params = OptionPlaceParams(
            orderList=[
                OptionOrderItemWithFastExec(orderId="Q-A", orderType="市价单"),
                OptionOrderItemWithFastExec(orderId="Q-B", orderType="POV", povRatio=20),
            ]
        )
        _patch_llm(monkeypatch, params)
        result = await option_extract_place(
            {"raw_text": "x", "intent": "place_order_from_quote"}
        )
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_extract_place"
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
        monkeypatch.setattr(ep_module, "get_qwen_thinking", lambda: fake_llm)
        result = await option_extract_place(
            {"raw_text": "x", "intent": "place_order_from_quote"}
        )
        assert result.get("error") is not None
        assert result["error"].node == "option_extract_place"
