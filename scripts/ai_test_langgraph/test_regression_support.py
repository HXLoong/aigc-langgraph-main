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
