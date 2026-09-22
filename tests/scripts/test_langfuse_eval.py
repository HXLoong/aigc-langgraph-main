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


def test_local_item_builds_judge_expectation_from_turn_assertions() -> None:
    """A 方言没有 expected.output：Judge 期望由逐轮 expected + 文本断言拼成，不能是空串。"""
    case = GoldenCase(
        id="case-030",
        category="option_close_case",
        turns=[
            TurnSpec(
                send_text="我想平仓",
                at_bot=True,
                expected={"product_type": "option_close", "intent": "close_order_query"},
                response_contains=["序号", "单号"],
                response_not_contains=["互换订单"],
            ),
            TurnSpec(
                send_text="确认平仓",
                quote_previous=True,
                expected={"intent": "close_order_confirm"},
                response_contains_any=["确认平仓成功", "平仓已提交"],
            ),
        ],
        expected={"product_type": "option_close", "intent": "close_order_query"},
    )
    text = _LocalItem(case).expected_output

    assert "第1轮" in text and "第2轮" in text
    assert "product_type=option_close, intent=close_order_query" in text
    assert "必含文本: 序号; 单号" in text
    assert "禁止文本: 互换订单" in text
    assert "任一文本: 确认平仓成功; 平仓已提交" in text
    assert "intent=close_order_confirm" in text


def test_local_item_records_suite_in_metadata() -> None:
    case = GoldenCase(id="intent-swap-1", category="intent/swap", turns=[TurnSpec(send_text="x")])
    assert _LocalItem(case, suite="intent").metadata["suite"] == "intent"
    assert _LocalItem(case).metadata["suite"] == "business"


def test_resolve_suite_from_local_paths_dataset_name_or_override() -> None:
    from pathlib import Path

    from scripts.langfuse.langfuse_eval import resolve_suite

    assert resolve_suite(None, [Path("tests/fixtures/intent")], None) == "intent"
    assert resolve_suite(None, [Path("tests/fixtures/intent/swap.jsonl")], None) == "intent"
    assert resolve_suite(None, [Path("tests/fixtures/categories")], None) == "business"
    assert resolve_suite(None, None, "intent-swap") == "intent"
    assert resolve_suite(None, None, "golden_option_inquiry_case") == "business"
    assert resolve_suite("intent", [Path("tests/fixtures/categories")], None) == "intent"


def test_intent_suite_never_runs_llm_judge() -> None:
    """意图集只用确定性 intent_match 评分。"""
    from scripts.langfuse.langfuse_eval import judge_enabled

    assert judge_enabled("intent", no_judge=False) is False
    assert judge_enabled("business", no_judge=False) is True
    assert judge_enabled("business", no_judge=True) is False


@pytest.mark.asyncio
async def test_dataset_dry_run_previews_categories_input_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """上传结构是 send_text + sub_scenes，预览不能只打印空输入。"""

    class FakeLangfuse:
        def get_dataset(self, _name: str) -> SimpleNamespace:
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        id="case-022",
                        input={"send_text": "快速询价", "sub_scenes": [{"send_text": "补充名义本金"}]},
                        metadata={},
                    )
                ]
            )

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    await run_eval("golden_option_inquiry_case", None, None, 1, None, True)

    assert "case-022: 快速询价; 补充名义本金" in capsys.readouterr().out
