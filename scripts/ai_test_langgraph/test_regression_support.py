"""回归断言的公开契约：任一包含、全部包含、全部不包含。"""
from __future__ import annotations

import pytest
from regression_support import evaluate_response


@pytest.mark.parametrize("candidates", ["  9618.HK \n JD.O \n ", [" 9618.HK ", "JD.O", ""]])
def test_contains_any_passes_when_one_normalized_candidate_matches(candidates):
    result = evaluate_response("标的代码：JD.O", {"response_contains_any": candidates})
    assert result.passed
    assert result.failures == []


@pytest.mark.parametrize("candidates", ["A\nB", ["A", "B"]])
def test_contains_any_reports_one_group_failure(candidates):
    result = evaluate_response("C", {"response_contains_any": candidates})
    assert not result.passed
    assert len(result.failures) == 1
    assert "A" in result.failures[0] and "B" in result.failures[0]


@pytest.mark.parametrize("candidates", [None, "", " \n ", [], ["", " "]])
def test_empty_contains_any_adds_no_constraint(candidates):
    assert evaluate_response("", {"response_contains_any": candidates}).passed


@pytest.mark.parametrize("scenario,passed,failures", [
    ({"response_contains": "A\nB"}, False, 1),
    ({"response_contains": ["A", "B"]}, False, 1),
    ({"response_contains": ["A"]}, True, 0),
    ({"response_not_contains": "A\nB"}, False, 1),
    ({"response_not_contains": ["A", "B"]}, False, 1),
    ({"response_not_contains": ["B"]}, True, 0),
    ({"response_contains_any": ["A", "B"], "response_contains": "B"}, False, 1),
    ({"response_contains_any": ["A", "B"], "response_not_contains": "A"}, False, 1),
])
def test_all_contains_and_not_contains_remain_independent(scenario, passed, failures):
    result = evaluate_response("A", scenario)
    assert result.passed is passed
    assert len(result.failures) == failures


def test_dynamic_order_id_tokens_match_fuzzy():
    """case-029：期望截断前缀 Q-2026，实际完整单号 → 动态值归一后断言通过。"""
    result = evaluate_response(
        "期权订单Q-20260918-2768122880：已收到您的下单请求，待交易员审核。",
        {"response_contains": "期权订单Q-2026：已收到您的下单请求，待交易员审核。"},
    )
    assert result.passed


def test_dynamic_contract_ids_match_fuzzy():
    result = evaluate_response(
        "平仓单号: CO-20260918-A1B2C3D4 已受理",
        {"response_contains": "平仓单号: CO-20260918-XXXXXXXX 已受理"},
    )
    assert result.passed


def test_judge_fallback_used_only_for_failed_contains_lines():
    calls: list[tuple[str, str]] = []

    def judge(line: str, answer: str) -> bool:
        calls.append((line, answer))
        return True

    result = evaluate_response("实际回复", {"response_contains": "语义等价片段"}, judge=judge)
    assert result.passed
    assert calls == [("语义等价片段", "实际回复")]


def test_judge_not_called_when_deterministic_contains_matches():
    calls: list[str] = []

    def judge(line: str, answer: str) -> bool:
        calls.append(line)
        return True

    result = evaluate_response("包含：语义等价片段", {"response_contains": "语义等价片段"}, judge=judge)
    assert result.passed
    assert calls == []


def test_judge_rejection_and_errors_keep_assertion_failure():
    rejected = evaluate_response(
        "实际回复", {"response_contains": "缺失片段"}, judge=lambda line, answer: False
    )
    assert not rejected.passed

    def broken_judge(line: str, answer: str) -> bool:
        raise RuntimeError("judge down")

    result = evaluate_response("实际回复", {"response_contains": "缺失片段"}, judge=broken_judge)
    assert not result.passed
    assert len(result.failures) == 1
