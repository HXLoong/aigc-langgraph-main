"""close.intent 节点测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.intent import (
    _JSON_OUTPUT_INSTRUCTION,
    _build_user_message,
    close_intent,
)
from app.subgraphs.close.models import CloseIntentOutput


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> AsyncMock:
    fake_output = CloseIntentOutput(type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        intent_module, "get_qwen_thinking", lambda: fake_base_llm
    )
    return fake_llm_with_schema.ainvoke


# ============================================================
# 工程适配：JSON 输出指令追加
# ============================================================


class TestJsonInstructionAppend:
    def test_json_instruction_constant_includes_type_field(self) -> None:
        """工程层追加的指令必须含 'type' 关键字 + 6 个 close 意图引用。"""
        assert "type" in _JSON_OUTPUT_INSTRUCTION
        assert "close_order_" in _JSON_OUTPUT_INSTRUCTION
        assert "unknown_intent" in _JSON_OUTPUT_INSTRUCTION


# ============================================================
# user message
# ============================================================


class TestBuildUserMessage:
    def test_includes_dify_inputs(self) -> None:
        msg = _build_user_message(
            {
                "raw_text": "我有哪些期权持仓",
                "quote_content": None,
                "history_messages": [],
            }
        )
        assert "raw_content: 我有哪些期权持仓" in msg
        assert "quote_content:" in msg
        assert "history_query_str:" in msg

    def test_handles_empty_state(self) -> None:
        msg = _build_user_message({})
        assert "raw_content:" in msg


# ============================================================
# 节点 mock LLM
# ============================================================


@pytest.mark.asyncio
class TestCloseIntentNode:
    async def test_classifies_holding_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "close_order_query")
        result = await close_intent({"raw_text": "我有哪些期权持仓"})
        assert result["intent"] == "close_order_query"

    async def test_classifies_place_close_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "close_order_request")
        result = await close_intent({"raw_text": "平 CO-20260304-4FE9C941 全部"})
        assert result["intent"] == "close_order_request"

    async def test_classifies_confirm_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "close_order_confirm")
        result = await close_intent({"raw_text": "确认平仓 CO-20260304-ABCD1234"})
        assert result["intent"] == "close_order_confirm"

    async def test_classifies_cancel_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "close_order_cancel_request")
        result = await close_intent({"raw_text": "撤销平仓单 CO-20260304-ABCD1234"})
        assert result["intent"] == "close_order_cancel_request"

    async def test_writes_trace_with_decision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "close_order_query")
        result = await close_intent({"raw_text": "查一下我现在的持仓"})
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "close_intent"
        assert "intent=close_order_query" in trace[0].decision

    async def test_passes_augmented_system_to_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """system message 末尾必须含追加的 JSON 指令。"""
        ainvoke = _patch_llm(monkeypatch, "close_order_query")
        await close_intent({"raw_text": "我想平仓"})
        messages = ainvoke.call_args[0][0]
        system_content = messages[0][1]
        assert "工程层输出格式约束" in system_content
        assert '"type"' in system_content

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
            intent_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await close_intent({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "close_intent"

    async def test_confirm_cancel_keyword_maps_to_valid_enum_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回归测试：历史 typo 把"确认撤单"规则覆盖写成不存在的枚举值
        `close_order_confirm_cancel`（正确顺序是 `close_order_cancel_confirm`），
        导致规则从未命中、静默 fall through 到 close_unknown。"""
        _patch_llm(monkeypatch, "close_order_query")  # LLM 误判，靠规则纠正
        result = await close_intent({"raw_text": "确认撤单 CO-20260304-ABCD1234"})
        assert result["intent"] == "close_order_cancel_confirm"
