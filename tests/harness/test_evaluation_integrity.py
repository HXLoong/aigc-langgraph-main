"""确定性评分必须识别缺失断言和未执行轮次，不能只检查有回复。"""
from __future__ import annotations

from harness.cli import _report_case, _turn_diffs
from harness.golden import GoldenCase, TurnSpec
from harness.multi_turn import MultiTurnResult, _extract_turn


def test_nonempty_reply_without_expectation_cannot_pass() -> None:
    """没有业务真值的输入只能记录不可评分原因。"""
    case = GoldenCase(id="unannotated", category="test", turns=[TurnSpec(send_text="test")])
    result = MultiTurnResult(case.id, "session", turns=[_extract_turn(1, case.turns[0], "", {"reply_text": "有回复"})])
    report = _report_case(case, result, _turn_diffs(case, result))
    assert not report["passed"]
    assert any(diff["path"] == "expected" for diff in report["turns"][0]["diff"])


def test_missing_turn_cannot_pass_when_failure_metadata_is_absent() -> None:
    """即使执行器没有附早停标记，缺少实际轮次仍必须失败。"""
    case = GoldenCase(id="incomplete", category="test", turns=[
        TurnSpec(send_text="one", expected={"intent": "new_inquiry"}),
        TurnSpec(send_text="two", expected={"intent": "confirm_order"}),
    ])
    result = MultiTurnResult(case.id, "session", turns=[_extract_turn(1, case.turns[0], "", {"intent": "new_inquiry"})])
    diffs = _turn_diffs(case, result)
    assert not _report_case(case, result, diffs)["passed"]
    assert diffs[2][0].path == "runtime"


def test_parameter_coverage_gap_is_reported_separately_from_existing_assertions() -> None:
    """用户确认先执行现有断言，写入参数标注缺口仍须显式可见。"""
    case = GoldenCase(id="coverage", category="option", turns=[{
        "send_text": "确认下单", "expected": {"intent": "confirm_order"},
    }])
    result = MultiTurnResult(case.id, "session", turns=[_extract_turn(1, case.turns[0], "", {"intent": "confirm_order"})])
    report = _report_case(case, result, _turn_diffs(case, result))
    assert report["passed"]
    assert report.get("parameter_assertion_coverage", {}).get("missing_turns") == [1]
    assert report["parameter_assertion_coverage"]["status"] == "pending_business_acceptance"


def test_intent_suite_does_not_claim_business_parameter_coverage() -> None:
    """意图标注的职责不同，不能把它的参数缺省列为业务标注缺口。"""
    from harness.evaluation import parameter_coverage

    case = GoldenCase(id="intent-only", category="intent/option", turns=[{
        "send_text": "确认下单", "expected": {"intent": "confirm_order"},
    }])
    assert parameter_coverage(case)["status"] == "not_applicable"
