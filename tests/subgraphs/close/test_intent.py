"""close.intent 节点测试（mock LLM）。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.intent import (
    SPEC,
    _build_user_message,
    close_intent,
)
from app.subgraphs.close.models import CloseIntentOutput
from tests.intent_fixtures import intent_reply, mock_ainvoke


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> AsyncMock:
    fake_output = intent_reply(CloseIntentOutput, type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = mock_ainvoke(fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        intent_module, "get_qwen_thinking", lambda: fake_base_llm
    )
    return fake_llm_with_schema.ainvoke


# ============================================================
# ADR 0023：输出契约由 with_structured_output 的 schema 承担
# ============================================================


class TestOutputContractLivesInSchema:
    def test_spec_declares_output_model_with_type_field(self) -> None:
        """不再在代码里追加 JSON 指令；type 枚举经 Pydantic schema 下发给 function calling。"""
        assert SPEC.output_model is CloseIntentOutput
        schema = CloseIntentOutput.model_json_schema()
        assert "type" in schema["properties"]
        enum_values = schema["properties"]["type"]["enum"]
        assert "unknown_intent" in enum_values
        assert any(v.startswith("close_order_") for v in enum_values)


# ============================================================
# user message
# ============================================================


class TestBuildUserMessage:
    def test_includes_declared_inputs(self) -> None:
        msg = _build_user_message(
            {
                "raw_text": "我有哪些期权持仓",
                "quote_content": None,
                "history_messages": [],
            }
        )
        assert json.loads(msg)["sources"]["raw"] == '我有哪些期权持仓'
        assert "quote" in json.loads(msg)["sources"]
        assert "source_roles" in json.loads(msg)

    def test_handles_empty_state(self) -> None:
        msg = _build_user_message({})
        assert json.loads(msg)["sources"]["raw"] == ''


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

    async def test_system_has_no_code_appended_format_instruction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0023：输出契约由 with_structured_output 的 schema 承担，代码不再往 system 末尾
        追加 JSON 指令（原 _JSON_OUTPUT_INSTRUCTION 违反"提示词不硬编码在代码里"）。"""
        ainvoke = _patch_llm(monkeypatch, "close_order_query")
        await close_intent({"raw_text": "我想平仓"})
        messages = ainvoke.call_args[0][0]
        system_content = messages[0][1]
        assert "工程层输出格式约束" not in system_content
        assert "evidence" in system_content and "confidence" in system_content

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


@pytest.mark.asyncio
class TestCancelKeywordOverride:
    """「撤单」关键词只在正面撤单指令时纠正模型；否定或查询语义以模型判定为准。"""

    @pytest.mark.parametrize(
        ("raw", "model_intent"),
        [
            ("不要撤单", "unknown_intent"),
            ("别撤单了，CO-20260304-4FE9C941 平200万", "close_order_request"),
            ("先不用撤单", "unknown_intent"),
            ("查询撤单状态 CO-20260304-4FE9C941", "close_order_order_query"),
            ("CO-20260304-4FE9C941 撤单成功了吗", "close_order_order_query"),
            ("撤单是否已经完成？", "close_order_order_query"),
        ],
    )
    async def test_negated_or_query_cancel_keeps_model_intent(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, model_intent: str
    ) -> None:
        _patch_llm(monkeypatch, model_intent)
        result = await close_intent({"raw_text": raw})
        assert result["intent"] == model_intent

    @pytest.mark.parametrize("raw", ["帮我撤单 CO-20260304-4FE9C941", "撤单第二笔"])
    async def test_positive_cancel_still_corrects_model(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        _patch_llm(monkeypatch, "close_order_query")
        result = await close_intent({"raw_text": raw})
        assert result["intent"] == "close_order_cancel_request"


@pytest.mark.asyncio
class TestDeterministicRulesStayInEnum:
    """提示词治理评估 OC-02：代码规则层写入的 intent 必须是 CloseIntentType 合法值。"""

    async def test_cancel_with_quoted_cancel_context_keeps_llm_intent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"取消" + 引用撤单请求：旧规则覆盖为不存在的 close_order_confirm_cancel，
        路由落到 close_unknown。提示词明文规定撤单类意图只看 raw_content、禁止用
        quote_content 判定（option_close/intent.md「quote_content 使用限制」），
        故规则应删除、以 LLM 判定为准。"""
        from typing import get_args

        from app.subgraphs.close.models import CloseIntentType

        _patch_llm(monkeypatch, "close_order_cancel_request")
        result = await close_intent(
            {"raw_text": "取消", "quote_content": "撤单请求 CO-20260304-4FE9C941 待确认"}
        )
        assert result["intent"] in get_args(CloseIntentType)
        assert result["intent"] == "close_order_cancel_request"

    def test_every_literal_intent_in_rule_layer_is_valid(self) -> None:
        import re
        from pathlib import Path
        from typing import get_args

        from app.subgraphs.close.models import CloseIntentType

        src = Path(intent_module.__file__).read_text(encoding="utf-8")
        assigned = set(re.findall(r'intent = "([a-z_]+)"', src))
        assert assigned, "未找到规则层赋值"
        assert assigned <= set(get_args(CloseIntentType)), assigned - set(get_args(CloseIntentType))
