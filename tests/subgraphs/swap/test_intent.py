"""swap.intent 节点测试（mock LLM，不联网）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap.intent import _format_history, _build_user_message, swap_intent
from app.subgraphs.swap.models import SwapIntentOutput


# ============================================================
# 辅助函数 _format_history
# ============================================================


class TestFormatHistory:
    def test_empty_history(self) -> None:
        assert _format_history(None) == ""
        assert _format_history([]) == ""

    def test_dict_history(self) -> None:
        history = [
            {"role": "user", "content": "做一笔互换"},
            {"role": "assistant", "content": "请提供标的"},
        ]
        result = _format_history(history)  # type: ignore[arg-type]
        assert "user: 做一笔互换" in result
        assert "assistant: 请提供标的" in result


# ============================================================
# _build_user_message
# ============================================================


class TestBuildUserMessage:
    def test_includes_all_four_dify_inputs(self) -> None:
        msg = _build_user_message(
            {
                "raw_text": "做一笔招商银行的 TRS",
                "quote_content": "（无引用）",
                "history_messages": [],
            }
        )
        assert "raw_content: 做一笔招商银行的 TRS" in msg
        assert "quote_content:" in msg
        assert "history_query_str:" in msg
        assert "bot_name_list:" in msg

    def test_handles_empty_state(self) -> None:
        msg = _build_user_message({})
        assert "raw_content:" in msg
        assert "bot_name_list:" in msg


# ============================================================
# 节点端到端（mock LLM）
# ============================================================


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, return_type: str
) -> AsyncMock:
    """让 swap.intent 调 LLM 时返回固定 SwapIntentOutput。"""
    fake_output = SwapIntentOutput(type=return_type)  # type: ignore[arg-type]

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


@pytest.mark.asyncio
class TestSwapIntentNode:
    async def test_classifies_place_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "place_order_request")
        result = await swap_intent({"raw_text": "做一笔招商银行的 TRS"})
        assert result["intent"] == "place_order_request"
        assert result["error"] is None if "error" in result else True

    async def test_writes_trace_with_decision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_llm(monkeypatch, "cancel_order_request")
        result = await swap_intent({"raw_text": "撤 H-20260304-0001"})
        trace = result.get("trace", [])
        assert len(trace) == 1
        assert trace[0].node == "swap_intent"
        assert "intent=cancel_order_request" in trace[0].decision

    async def test_passes_quote_and_history_to_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ainvoke = _patch_llm(monkeypatch, "confirm_order")
        await swap_intent(
            {
                "raw_text": "确认",
                "quote_content": "互换订单 H-20260304-0001 已生成",
                "history_messages": [],
            }
        )
        # LLM 被调一次，user message 含 quote_content
        assert ainvoke.call_count == 1
        messages = ainvoke.call_args[0][0]
        user_msg_content = messages[-1][1]
        assert "互换订单 H-20260304-0001 已生成" in user_msg_content

    async def test_safe_node_catches_llm_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM 抛错 → @safe_node 写 state['error']，不让图崩。"""
        fake_llm = MagicMock()
        fake_llm.with_structured_output = MagicMock(
            return_value=MagicMock(
                ainvoke=AsyncMock(side_effect=RuntimeError("LLM down"))
            )
        )
        monkeypatch.setattr(
            intent_module, "get_qwen_thinking", lambda: fake_llm
        )
        result = await swap_intent({"raw_text": "x"})
        assert result.get("error") is not None
        assert result["error"].node == "swap_intent"
        assert "LLM down" in result["error"].message
