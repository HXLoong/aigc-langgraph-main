"""意图集确定性评估器：逐轮比对 expected.product_type / intent 与实际路由结果。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness.evaluators.intent_match import evaluate

ROOT = Path(__file__).resolve().parents[2]


def _context(*, expected_output: object, output: object) -> SimpleNamespace:
    return SimpleNamespace(
        experiment=SimpleNamespace(item_expected_output=expected_output),
        observation=SimpleNamespace(output=output),
    )


def test_intent_match_passes_when_every_turn_matches() -> None:
    result = evaluate(
        _context(
            expected_output={
                "expected": {"product_type": "option_close", "intent": "close_order_query"},
                "sub_scenes": [
                    {"expected": {"product_type": "option_close", "intent": "close_order_request"}},
                    {"expected": {"product_type": "option_close", "intent": "close_order_confirm"}},
                ],
            },
            output={
                "turns": [
                    {"product_type": "option_close", "intent": "close_order_query"},
                    {"product_type": "option_close", "intent": "close_order_request"},
                    {"product_type": "option_close", "intent": "close_order_confirm"},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.name == "det_intent_match_pass"
    assert score.data_type == "BOOLEAN"
    assert score.value is True
    assert score.metadata == {"assertion_count": 6, "mismatch_count": 0}


def test_intent_match_reports_turn_field_expected_and_actual() -> None:
    result = evaluate(
        _context(
            expected_output={
                "expected": {"product_type": "swap", "intent": "place_order_request"},
                "sub_scenes": [
                    {"expected": {"product_type": "swap", "intent": "confirm_order"}},
                ],
            },
            output={
                "turns": [
                    {"product_type": "swap", "intent": "place_order_request"},
                    {"product_type": "swap", "intent": "unknown_intent"},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.value is False
    assert "第 2 轮 intent 不符：期望 confirm_order，实际 unknown_intent" in (score.comment or "")
    assert score.metadata == {"assertion_count": 4, "mismatch_count": 1}


def test_intent_match_fails_when_actual_turn_is_missing() -> None:
    """早停后未执行的轮次不能静默通过。"""
    result = evaluate(
        _context(
            expected_output={
                "expected": {"product_type": "option", "intent": "new_inquiry"},
                "sub_scenes": [
                    {"expected": {"product_type": "option", "intent": "place_order_from_quote"}},
                ],
            },
            output={"turns": [{"product_type": "option", "intent": "new_inquiry"}]},
        )
    )

    score = result.scores[0]
    assert score.value is False
    assert "第 2 轮无实际输出" in (score.comment or "")


def test_intent_match_only_checks_keys_present_in_expected() -> None:
    """product_type=unknown 的反案例可以不标 intent；没有 expected 的轮次不计断言。"""
    result = evaluate(
        _context(
            expected_output={
                "expected": {"product_type": "unknown"},
                "sub_scenes": [{"response_contains": ["无关文本断言"]}],
            },
            output={
                "turns": [
                    {"product_type": "unknown", "intent": None},
                    {"product_type": "swap", "intent": "place_order_request"},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.value is True
    assert score.metadata == {"assertion_count": 1, "mismatch_count": 0}


def test_intent_match_accepts_json_string_payloads_and_single_turn_output() -> None:
    result = evaluate(
        _context(
            expected_output=json.dumps(
                {"expected": {"product_type": "swap", "intent": "query_order_status"}}
            ),
            output=json.dumps({"product_type": "swap", "intent": "query_order_status"}),
        )
    )

    assert result.scores[0].value is True


def test_intent_match_without_any_assertion_is_a_failure_not_a_pass() -> None:
    """意图集用例必须带 expected；空断言通过会掩盖标注缺失。"""
    result = evaluate(
        _context(expected_output={"response_contains": ["x"]}, output={"turns": []})
    )

    score = result.scores[0]
    assert score.value is False
    assert "没有可比对的 expected.product_type / intent" in (score.comment or "")


def test_intent_match_is_registered_as_langfuse_evaluator() -> None:
    definitions = json.loads(
        (ROOT / "scripts" / "langfuse" / "definitions" / "evaluators.json").read_text(
            encoding="utf-8"
        )
    )
    by_name = {item["name"]: item for item in definitions["evaluators"]}

    assert by_name["intent-match"]["score_name"] == "det_intent_match_pass"
    assert by_name["intent-match"]["source"] == "harness/evaluators/intent_match.py"
    assert (ROOT / by_name["intent-match"]["source"]).is_file()
