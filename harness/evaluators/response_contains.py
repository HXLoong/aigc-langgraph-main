"""Langfuse Code Evaluator：回复必须包含用例指定的全部文本。"""

from __future__ import annotations

import json
import re
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


def _lines(value: Any) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


_ORDER_ID_RE = re.compile(r"(?<![A-Za-z0-9])Q-\d{4,}(?:-[A-Za-z0-9]+)?")
_GENERIC_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{1,4}-\d{6,}(?:-[A-Za-z0-9]+)?")


def _normalize(text: str) -> str:
    return _GENERIC_ID_RE.sub("{id}", _ORDER_ID_RE.sub("Q-{id}", text))


def evaluate(ctx: Any) -> EvaluationResult:
    """对 Experiment Item 的每轮回复生成一个 Boolean Score。"""
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

    missing: list[str] = []
    assertion_count = 0
    for index, expected_turn in enumerate(expected_turns):
        actual_turn = actual_turns[index] if index < len(actual_turns) else {}
        reply_text = (
            str(actual_turn.get("reply_text") or "")
            if isinstance(actual_turn, dict)
            else str(actual_turn or "")
        )
        normalized_reply = _normalize(reply_text)
        for required in _lines(expected_turn.get("response_contains")):
            assertion_count += 1
            if _normalize(required) not in normalized_reply:
                missing.append(f"第 {index + 1} 轮缺少必含文本：{required}")

    passed = not missing
    return EvaluationResult(
        scores=[
            Score(
                name="det_required_text_pass",
                value=passed,
                data_type="BOOLEAN",
                comment="全部必含文本均已出现" if passed else "；".join(missing),
                metadata={
                    "assertion_count": assertion_count,
                    "missing_count": len(missing),
                },
            )
        ]
    )
