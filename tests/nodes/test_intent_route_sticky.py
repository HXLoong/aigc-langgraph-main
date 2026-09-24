"""一级路由多轮粘性——规则与 LLM 双 unknown 时继承上一轮 product_type。

修复对象：裸发「确认下单」「200万」等跟进指令 → LLM 兜底判 unknown → fallback
打断对话；checkpoint 里明明有上一轮 product_type 却不利用。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import app.nodes.intent_route as ir
from tests.intent_fixtures import route_reply


@pytest.fixture()
def _llm_unknown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ir, "_classify_with_llm", AsyncMock(side_effect=lambda text, quote, history=None: route_reply("unknown", text)))


class TestSticky:
    async def test_double_unknown_inherits_previous_product(
        self, _llm_unknown: None
    ) -> None:
        state = {"raw_text": "确认下单", "product_type": "swap"}
        out = await ir.intent_route(state)
        assert out["product_type"] == "swap"
        assert "sticky" in out["trace"][0].decision

    async def test_sticky_option_close(self, _llm_unknown: None) -> None:
        state = {"raw_text": "200万", "product_type": "option_close"}
        out = await ir.intent_route(state)
        assert out["product_type"] == "option_close"

    async def test_no_previous_stays_unknown(self, _llm_unknown: None) -> None:
        state = {"raw_text": "随便说点什么完全无关的"}
        out = await ir.intent_route(state)
        assert out["product_type"] == "unknown"

    async def test_previous_unknown_not_inherited(self, _llm_unknown: None) -> None:
        state = {"raw_text": "呵呵", "product_type": "unknown"}
        out = await ir.intent_route(state)
        assert out["product_type"] == "unknown"

    async def test_llm_answer_beats_sticky(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ir, "_classify_with_llm", AsyncMock(side_effect=lambda text, quote, history=None: route_reply("期权-文本", text)))
        state = {"raw_text": "帮我看看那个结构", "product_type": "swap"}
        out = await ir.intent_route(state)
        assert out["product_type"] == "option"

    async def test_rule_hit_ignores_previous(self, _llm_unknown: None) -> None:
        state = {"raw_text": "买入 贵州茅台 10000股 POV 20%", "product_type": "option"}
        out = await ir.intent_route(state)
        assert out["product_type"] == "swap"


def test_turn_state_entry_does_not_reset_product_type() -> None:
    """入口不写 product_type，让 intent_route 的粘性继承读 checkpoint（ADR 0024：入口 = routes 同一路径）。"""
    from app.api.turn_state import inputs_to_state

    state = inputs_to_state({"rawContent": "确认下单", "conversationId": "c1"})
    assert "product_type" not in state
