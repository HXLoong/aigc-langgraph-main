"""swap.intent 节点测试（mock LLM，不联网）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap.intent import _build_user_message, _format_shortname_list, swap_intent
from app.subgraphs.swap.models import SwapIntentOutput

# ============================================================
# 辅助函数 _format_shortname_list
# ============================================================


class TestFormatShortnameList:
    def test_empty_or_none(self) -> None:
        assert _format_shortname_list(None) == ""
        assert _format_shortname_list([]) == ""

    def test_joins_shortnames(self) -> None:
        counterparties = [
            {"ctptyId": "1", "shortName": "临沂阿凡提", "longName": "临沂阿凡提有限公司", "sort": "A"},
            {"ctptyId": "2", "shortName": "测试111", "longName": "测试有限公司", "sort": "B"},
        ]
        result = _format_shortname_list(counterparties)
        assert "临沂阿凡提" in result
        assert "测试111" in result


# ============================================================
# _build_user_message
# ============================================================


class TestBuildUserMessage:
    def test_includes_three_dsl_v2_inputs(self) -> None:
        msg = _build_user_message(
            {
                "raw_text": "做一笔招商银行的 TRS",
                "quote_content": "（无引用）",
                "swap_counterparties": [{"shortName": "打火机", "sort": "A"}],
            }
        )
        assert "raw_content：做一笔招商银行的 TRS" in msg
        assert "quote_content：" in msg
        assert "shortname_list：打火机" in msg

    def test_handles_empty_state(self) -> None:
        msg = _build_user_message({})
        assert "raw_content：" in msg
        assert "shortname_list：" in msg


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

    async def test_passes_quote_and_counterparties_to_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ainvoke = _patch_llm(monkeypatch, "confirm_order")
        await swap_intent(
            {
                "raw_text": "确认",
                "quote_content": "互换订单 H-20260304-0001 已生成",
                "swap_counterparties": [{"shortName": "打火机", "sort": "A"}],
            }
        )
        # LLM 被调一次，user message 含 quote_content + shortname_list
        assert ainvoke.call_count == 1
        messages = ainvoke.call_args[0][0]
        user_msg_content = messages[-1][1]
        assert "互换订单 H-20260304-0001 已生成" in user_msg_content
        assert "打火机" in user_msg_content

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


@pytest.mark.asyncio
class TestConfirmKeywordPreRoute:
    """提示词治理评估 SW-INC-01：2026-09-11 回归 Dify 原文后，intent.md 的意图枚举不再含
    confirm_order（Dify 把「确认下单」交给 code 节点 1755072896717 + if-else 1781200000774
    前置分流），而 app 仍靠 LLM 输出 confirm_order 路由到 swap_confirm。这里移植同款
    确定性前置：raw 含「确认下单/确定下单/确认订单/下单确认」→ confirm_order，不调 LLM。"""

    @pytest.mark.parametrize("raw", ["确认下单", "确定下单 H-20260901-0000000001", "确认订单", "下单确认"])
    async def test_confirm_keyword_routes_without_llm(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        ainvoke = _patch_llm(monkeypatch, "place_order_request")  # LLM 若被调会误判
        result = await swap_intent({"raw_text": raw, "quote_content": "互换订单 H-20260901-0000000001"})
        assert result["intent"] == "confirm_order"
        ainvoke.assert_not_called()

    async def test_no_keyword_still_uses_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ainvoke = _patch_llm(monkeypatch, "place_order_request")
        result = await swap_intent({"raw_text": "临沂阿凡提", "quote_content": "请回复【确认下单】"})
        assert result["intent"] == "place_order_request"
        ainvoke.assert_called_once()
