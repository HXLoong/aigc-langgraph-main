"""意图级 runner：只跑意图子链，冻结上下文，不碰任何后端（意图集只依赖 LLM）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.nodes.intent_route as intent_route_mod
import app.subgraphs.close.intent as close_intent_mod
import app.subgraphs.option.intent as option_intent_mod
import app.subgraphs.swap.intent as swap_intent_mod
import app.subgraphs.swap.place_order as swap_place_mod
from app.graph.state import Message
from harness import intent_runner
from harness.golden import load_golden

INTENT_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "intent"


def test_intent_graph_only_contains_intent_chain_nodes() -> None:
    """意图子链之外（参数抽取后的提交、render、persist、GOATS 快速分支）一律不在图里。"""
    graph = intent_runner.build_intent_graph()
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"ingest", "pre_route", "intent_route", "swap_intent", "option_intent", "close_intent"}

    with_extraction = intent_runner.build_intent_graph(swap_extraction=True)
    extra = set(with_extraction.get_graph().nodes) - nodes - {"__start__", "__end__"}
    assert extra == {"swap_place_order"}


def test_turn_state_injects_frozen_context() -> None:
    state = intent_runner.turn_state(
        {
            "send_text": "确认平仓",
            "at_bot": False,
            "quote_content": "以下平仓申请，请核对详情后确认：单号：CO-20260506-DEAF117C",
            "history": [
                {"role": "user", "content": "我想平仓"},
                {"role": "assistant", "content": "以下是您的期权持仓："},
            ],
            "prev_product_type": "option_close",
        },
        conversation_id="conv-1",
    )
    assert state["raw_text"] == "确认平仓"
    assert state["quote_content"] == "以下平仓申请，请核对详情后确认：单号：CO-20260506-DEAF117C"
    assert state["conversation_id"] == "conv-1"
    assert state["product_type"] == "option_close"
    history = state["history_messages"]
    assert [(m.role, m.content) for m in history] == [
        ("user", "我想平仓"),
        ("assistant", "以下是您的期权持仓："),
    ]
    assert all(isinstance(m, Message) for m in history)


def test_turn_state_injects_authorized_counterparties_like_production_input() -> None:
    """对手列表与 main 的 CI mock 授权上下文同源，进程内读取、不走网络。"""
    from mock_api.backend.fixtures import COUNTERPARTIES

    state = intent_runner.turn_state({"send_text": "买入京东"}, conversation_id="c")
    for field in ("option_counterparties_raw", "swap_counterparties_raw"):
        assert json.loads(state[field]) == COUNTERPARTIES


def test_requires_replay_classifies_frozen_and_replay_cases() -> None:
    frozen = [
        {"send_text": "查持仓", "quote_previous": False},
        {"send_text": "确认平仓", "quote_content": "单号：CO-20260506-DEAF117C"},
        {"send_text": "撤单", "quote_previous": False},
    ]
    assert intent_runner.requires_replay(frozen) is False
    assert intent_runner.requires_replay([{"send_text": "查持仓"}]) is False
    assert intent_runner.requires_replay([*frozen[:1], {"send_text": "确认", "quote_previous": True}]) is True
    # 子轮 quote_previous 缺省 = 引用第 1 轮回复，同样需要回放
    assert intent_runner.requires_replay([*frozen[:1], {"send_text": "确认"}]) is True
    assert intent_runner.requires_replay([{"send_text": "查询 {{previous_order_id}} 状态"}]) is True


def test_turn_state_without_context_has_no_quote_history_or_product() -> None:
    state = intent_runner.turn_state({"send_text": "查持仓", "at_bot": True}, conversation_id="c")
    assert not state.get("quote_content")
    assert not state.get("history_messages")
    assert "product_type" not in state


# ── 零后端不变量：全部意图集用例在“假 LLM + 封死网络”下跑完意图子链 ──


class _FakeStructured:
    def __init__(self, model: Any, raw: dict[str, str]) -> None:
        self._model = model
        self._raw = raw

    async def ainvoke(self, messages: Any) -> Any:
        if self._model is swap_place_mod.CANDIDATE_MODEL:
            return self._model.model_validate({})
        # 证据必须是本轮原文片段，才能通过 intent_records 的原文校验
        base = {"confidence": 0.9, "evidence": [{"text": self._raw["text"][:1], "origin": "raw"}]}
        name = self._model.__name__
        if name == "UnknownIntentOutput":
            return self._model(label="unknown", **base)
        intent = {
            "SwapIntentOutput": "place_order_request",
            "OptionIntentOutput": "new_inquiry",
            "CloseIntentOutput": "close_order_request",
        }[name]
        return self._model(type=intent, **base)


class _FakeLLM:
    def __init__(self, raw: dict[str, str]) -> None:
        self._raw = raw

    def with_structured_output(self, model: Any, **_: Any) -> _FakeStructured:
        return _FakeStructured(model, self._raw)


@pytest.mark.asyncio
async def test_every_intent_fixture_turn_runs_without_any_backend_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw: dict[str, str] = {"text": ""}
    calls: list[str] = []

    async def _blocked_send(self: httpx.AsyncClient, request: httpx.Request, *args: Any, **kwargs: Any) -> Any:
        calls.append(str(request.url))
        raise RuntimeError(f"network blocked in intent runner test: {request.url}")

    monkeypatch.setattr(httpx.AsyncClient, "send", _blocked_send)
    fake = _FakeLLM(raw)
    for module, attr in (
        (intent_route_mod, "get_qwen_thinking"),
        (swap_intent_mod, "get_qwen_thinking"),
        (option_intent_mod, "get_qwen_structured"),
        (close_intent_mod, "get_qwen_thinking"),
        (swap_place_mod, "get_qwen_complex"),
    ):
        monkeypatch.setattr(module, attr, lambda *a, **k: fake)

    graph = intent_runner.build_intent_graph(swap_extraction=True)
    cases = [
        case for case in load_golden(INTENT_FIXTURES)
        if not intent_runner.requires_replay([turn.model_dump() for turn in case.turns])
    ]
    assert len(cases) >= 380, "frozen intent cases unexpectedly shrank"
    turns = 0
    for case in cases:
        for index, turn in enumerate(case.turns):
            raw["text"] = turn.send_text
            result = await intent_runner.run_turn(
                graph, turn.model_dump(), conversation_id=f"{case.id}-{index}"
            )
            assert result.get("error") is None, (case.id, index, result.get("error"))
            assert result.get("product_type"), (case.id, index)
            turns += 1
    assert turns >= len(cases)
    assert calls == []


def test_frozen_close_cases_do_not_need_replay() -> None:
    """已冻结的平仓多轮用例必须能在纯 LLM 模式下执行。"""
    by_id = {case.id: case for case in load_golden([INTENT_FIXTURES / "option_close.jsonl"])}
    for case_id in ("intent-option_close-case-030", "intent-option_close-case-032", "intent-option_close-case-033"):
        turns = [turn.model_dump() for turn in by_id[case_id].turns]
        assert intent_runner.requires_replay(turns) is False, case_id
