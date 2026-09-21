"""LangFuse Judge regression tests."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import langfuse
import pytest

from harness.golden import GoldenCase, TurnSpec
from scripts.langfuse.langfuse_eval import (
    _LocalItem,
    _print_report,
    _run_graph_once,
    judge_by_deepseek,
    run_eval,
)


def test_print_report_supports_structured_dataset_item_without_judge(
    capsys: pytest.CaptureFixture[str],
) -> None:
    item = SimpleNamespace(
        input={
            "send_text": "快速询价",
            "sub_scenes": [{"send_text": "补充名义本金"}],
        },
        expected_output={
            "response_contains": ["场外期权询价详情"],
            "response_not_contains": ["未搜索到相关标的信息"],
        },
    )
    result = SimpleNamespace(
        item_results=[
            SimpleNamespace(item=item, output={"turns": []}, evaluations=[])
        ]
    )

    _print_report("no-judge-run", result)

    output = capsys.readouterr().out
    assert "输入: 快速询价; 补充名义本金" in output
    assert '"response_contains": ["场外期权询价详情"]' in output
    assert "未评分 case (1)" in output
    assert "[未评分]" in output
    assert "零分: 1" not in output


@pytest.mark.asyncio
async def test_dataset_experiment_no_judge_does_not_register_evaluator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class FakeLangfuse:
        def get_dataset(self, _name: str) -> SimpleNamespace:
            return SimpleNamespace(items=[])

        def run_experiment(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return SimpleNamespace(name="no-judge-run", item_results=[])

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)

    await run_eval(
        "golden_option_inquiry_case",
        None,
        None,
        1,
        None,
        False,
        no_judge=True,
    )

    assert "evaluators" not in captured


async def test_run_graph_once_uses_15_digit_numeric_message_id() -> None:
    """Eval message IDs must satisfy the Java Long contract."""
    captured_state: dict = {}

    class FakeGraph:
        async def ainvoke(self, state, config):  # type: ignore[no-untyped-def]
            captured_state.update(state)
            return state

    await _run_graph_once(
        FakeGraph(),
        {"configurable": {"thread_id": "eval-thread"}},
        raw_content="我想平仓",
    )

    message_id = captured_state["message_id"]
    assert isinstance(message_id, int)
    assert 100_000_000_000_000 <= message_id <= 999_999_999_999_999


def test_local_item_uses_active_fixture_turns() -> None:
    case = GoldenCase(
        id="case-025",
        category="option/place_from_quote",
        turns=[
            TurnSpec(send_text="询价", at_bot=True),
            TurnSpec(send_text="市价下单", quote_previous=True),
        ],
        expected={"product_type": "option", "intent": "new_inquiry", "output": "judge"},
        expected_output="judge",
    )
    item = _LocalItem(case)
    assert [turn["send_text"] for turn in item.input["turns"]] == ["询价", "市价下单"]
    assert item.input["turns"][1]["quote_previous"] is True
    assert item.expected_output == "judge"


def test_judge_does_not_return_json_parse_failure_after_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A textless first response must not become a JSON parsing failure."""

    class FakeMessages:
        def __init__(self) -> None:
            self.call_count = 0

        def create(self, **kwargs):  # type: ignore[no-untyped-def]
            self.call_count += 1
            if self.call_count == 1:
                return SimpleNamespace(
                    content=[SimpleNamespace(type="thinking", thinking="still reasoning")],
                    stop_reason="max_tokens",
                )
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"pass":true,"score":1.0,"reason":"expected result"}',
                    )
                ],
                stop_reason="end_turn",
            )

    class FakeAnthropic:
        def __init__(self) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)

    evaluation = judge_by_deepseek(
        output={"reply_text": "order placed"},
        expected_output="order placed successfully",
        metadata={"overview": "swap order placement"},
    )

    assert evaluation.value == 1.0
    assert evaluation.comment == "expected result"
    assert not evaluation.comment.startswith("JSON")
