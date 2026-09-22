"""Langfuse Code Evaluator：回复不得包含 fixture 中的禁止文本。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class Score:
    name: str
    value: int | float | str | bool
    data_type: str
    comment: str | None = None
    config_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class EvaluationResult:
    scores: list[Score]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _forbidden_lines(value: Any) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def evaluate(ctx: Any) -> EvaluationResult:
    """对 Experiment Item 的完整多轮回复生成一个 Boolean Score。"""
    experiment = getattr(ctx, "experiment", None)
    expected_output = _json_object(
        getattr(experiment, "item_expected_output", None) if experiment else None
    )
    output = _json_object(getattr(ctx.observation, "output", None))

    expected_turns = [expected_output]
    sub_scenes = expected_output.get("sub_scenes")
    if isinstance(sub_scenes, list):
        expected_turns.extend(item for item in sub_scenes if isinstance(item, dict))

    actual_turns = output.get("turns")
    if not isinstance(actual_turns, list):
        actual_turns = [output]

    violations: list[str] = []
    for index, expected_turn in enumerate(expected_turns):
        actual_turn = actual_turns[index] if index < len(actual_turns) else {}
        reply_text = (
            str(actual_turn.get("reply_text") or "")
            if isinstance(actual_turn, dict)
            else str(actual_turn or "")
        )
        for forbidden in _forbidden_lines(expected_turn.get("response_not_contains")):
            if forbidden in reply_text:
                violations.append(f"第 {index + 1} 轮命中禁止文本：{forbidden}")

    passed = not violations
    comment = "未命中禁止文本。" if passed else "；".join(violations)
    return EvaluationResult(
        scores=[
            Score(
                name="det_forbidden_text_pass",
                value=passed,
                data_type="BOOLEAN",
                comment=comment,
                metadata={"violation_count": len(violations)},
            )
        ]
    )
