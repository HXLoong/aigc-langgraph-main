from __future__ import annotations

from types import SimpleNamespace

from harness.evaluators.response_not_contains import evaluate


def _context(*, expected_output: dict, output: dict) -> SimpleNamespace:
    return SimpleNamespace(
        experiment=SimpleNamespace(item_expected_output=expected_output),
        observation=SimpleNamespace(output=output),
    )


def test_response_not_contains_passes_when_all_turns_are_clean() -> None:
    result = evaluate(
        _context(
            expected_output={
                "response_not_contains": ["未搜索到"],
                "sub_scenes": [{"response_not_contains": ["【待补充】"]}],
            },
            output={
                "turns": [
                    {"reply_text": "场外期权询价详情"},
                    {"reply_text": "名义本金：100万"},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.name == "det_forbidden_text_pass"
    assert score.data_type == "BOOLEAN"
    assert score.value is True


def test_response_not_contains_reports_turn_and_matched_text() -> None:
    result = evaluate(
        _context(
            expected_output={
                "response_not_contains": ["未搜索到"],
                "sub_scenes": [{"response_not_contains": ["【待补充】"]}],
            },
            output={
                "turns": [
                    {"reply_text": "场外期权询价详情"},
                    {"reply_text": "名义本金：【待补充】"},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.value is False
    assert "第 2 轮" in (score.comment or "")
    assert "【待补充】" in (score.comment or "")
