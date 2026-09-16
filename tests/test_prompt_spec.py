"""ADR 0023 · 提示词即代码：PromptSpec 把 LLM 节点的输入（AgentState 字段）、输出（Pydantic 模型）、
system 占位符渲染、user 消息拼装声明为一个代码对象，替代每个节点手拼的 _build_user_message /
_format_history / str.replace。"""
from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import BaseModel, Field

from app.graph.state import AgentState, Message
from app.prompts import blocks
from app.prompts import spec as spec_mod
from app.prompts.spec import PromptSpec


class _Out(BaseModel):
    type: str = Field(description="意图")


def _spec(**kw) -> PromptSpec:
    base = dict(
        category="option_close",
        name="holding_query",
        output_model=_Out,
        inputs=("raw_text", "option_counterparties"),
        user_builder=lambda s: f"用户输入：{s.get('raw_text', '')}",
        injects={"{{#1772773805306.optionListStr#}}": lambda s: blocks.json_list(s.get("option_counterparties"))},
    )
    base.update(kw)
    return PromptSpec(**base)


# ============================================================
# PromptSpec 契约
# ============================================================


class TestPromptSpec:
    def test_build_messages_renders_injects_and_user(self):
        s = _spec()
        state: AgentState = {"raw_text": "查对手阿凡提的持仓", "option_counterparties": [{"ctptyId": 1, "shortName": "阿凡提"}]}
        messages, prompt_name = s.build_messages(state)
        assert prompt_name == "holding_query"
        (role_s, system), (role_u, user) = messages
        assert role_s == "system" and role_u == "user"
        assert "{{#1772773805306.optionListStr#}}" not in system
        assert "阿凡提" in system
        assert user == "用户输入：查对手阿凡提的持仓"

    def test_unknown_state_field_is_rejected(self):
        with pytest.raises(ValueError, match="AgentState"):
            _spec(inputs=("raw_text", "no_such_field"))

    def test_inject_placeholder_must_exist_in_system(self):
        s = _spec(injects={"{{#nope#}}": lambda s: "x"})
        with pytest.raises(ValueError, match="占位符"):
            s.build_messages({"raw_text": "x"})

    def test_gray_spec_uses_versions_yaml(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OTC_PROMPT_SWAP_INTENT_VERSION", "intent")
        s = PromptSpec("swap", "intent", _Out, inputs=("raw_text",), user_builder=lambda st: "u", gray=True)
        _, prompt_name = s.build_messages({"raw_text": "x", "conversation_id": "c1"})
        assert prompt_name == "intent"


# ============================================================
# 共享积木（替代 10 份 _format_history 拷贝）
# ============================================================


class TestBlocks:
    def test_format_history_accepts_models_and_dicts(self):
        hist = [Message(role="user", content="a"), {"role": "assistant", "content": "b"}]
        assert blocks.format_history(hist) == "user: a\nassistant: b"
        assert blocks.format_history(None) == ""

    def test_shortnames(self):
        cps = [{"shortName": "甲"}, {"shortName": None}, {"shortName": "乙"}]
        assert blocks.shortnames(cps) == ["甲", "乙"]
        assert blocks.shortnames(None) == []

    def test_kv_block(self):
        assert blocks.kv_block(("raw_content", "x"), ("quote_content", "")) == "raw_content: x\n\nquote_content: "


# ============================================================
# 注册表：AgentState / 输出模型契约一致
# ============================================================


def _load_all_nodes() -> None:
    import importlib

    for mod in (
        "app.subgraphs.option.intent",
        "app.subgraphs.option.extract_inquiry",
        "app.subgraphs.option.extract_place",
        "app.subgraphs.option.extract_confirm_place",
        "app.subgraphs.option.extract_cancel_place",
        "app.subgraphs.option.extract_confirm_cancel",
        "app.subgraphs.option.extract_cancel",
        "app.subgraphs.option.extract_query",
        "app.subgraphs.close.intent",
        "app.subgraphs.close.holding_query",
        "app.subgraphs.swap.intent",
        "app.subgraphs.swap.place_order",
    ):
        importlib.import_module(mod)


class TestRegistry:
    def test_pilot_nodes_registered(self):
        _load_all_nodes()
        keys = set(spec_mod.all_specs())
        assert {
            "option/intent", "option/extract_inquiry", "option/extract_place", "option/extract_confirm_place",
            "option/extract_cancel_place", "option/extract_confirm_cancel", "option/extract_cancel",
            "option/extract_query", "option_close/intent", "option_close/holding_query", "swap/intent",
            "swap/place_order",
        } <= keys

    def test_inputs_are_agent_state_fields(self):
        _load_all_nodes()
        fields = set(get_type_hints(AgentState))
        for key, s in spec_mod.all_specs().items():
            assert set(s.inputs) <= fields, (key, set(s.inputs) - fields)

    def test_output_models_fully_described(self):
        """Pydantic 模型是输出契约的唯一真源：每个字段都要有 description，
        function calling 才能把字段语义传给模型，提示词里的 JSON 骨架才可以删。"""
        _load_all_nodes()
        missing = []
        for key, s in spec_mod.all_specs().items():
            for model, field, _ in spec_mod.iter_fields(s.output_model):
                if not field.description:
                    missing.append(f"{key}:{model.__name__}.{field.alias or '?'}")
        assert not missing, missing
