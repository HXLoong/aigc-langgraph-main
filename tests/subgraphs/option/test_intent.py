"""option.intent 节点测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import intent as intent_module
from app.subgraphs.option.intent import _build_user_message, option_intent
from app.subgraphs.option.models import OptionIntentOutput


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> AsyncMock:
    fake_output = OptionIntentOutput(type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        intent_module, "get_qwen_structured", lambda: fake_base_llm
    )
    return fake_llm_with_schema.ainvoke


# ============================================================
# user message 组装
# ============================================================


class TestBuildUserMessage:
    def test_includes_all_four_dify_inputs(self) -> None:
        msg = _build_user_message(
            {
                "raw_text": "期权询价 腾讯 1个月",
                "quote_content": None,
                "history_messages": [],
            }
        )
        assert "raw_content: 期权询价 腾讯 1个月" in msg
        assert "quote_content:" in msg
        assert "history_query_str:" in msg
        assert "bot_name_list:" in msg

    def test_handles_empty_state(self) -> None:
        msg = _build_user_message({})
        assert "raw_content:" in msg


# ============================================================
# 节点 mock LLM 端到端
# ============================================================


@pytest.mark.asyncio
class TestOptionIntentNode:
    async def test_classifies_new_inquiry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "new_inquiry")
        result = await option_intent({"raw_text": "期权询价 腾讯控股 1个月"})
        assert result["intent"] == "new_inquiry"

    async def test_classifies_place_order_from_quote(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "place_order_from_quote")
        result = await option_intent(
            {"raw_text": "期权下单 茅台 欧式看涨 行权价 1800"}
        )
        assert result["intent"] == "place_order_from_quote"

    async def test_classifies_request_cancel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "request_cancel_order")
        result = await option_intent(
            {"raw_text": "期权撤单 OPT-20260304-0001"}
        )
        assert result["intent"] == "request_cancel_order"

    async def test_writes_trace_with_decision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "confirm_order")
        result = await option_intent({"raw_text": "确认第二笔"})
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "option_intent"
        assert "intent=confirm_order" in trace[0].decision

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
            intent_module, "get_qwen_structured", lambda: fake_llm
        )
        result = await option_intent({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "option_intent"
