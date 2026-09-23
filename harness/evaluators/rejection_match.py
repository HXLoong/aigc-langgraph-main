"""Langfuse 独立拒绝验收：明确拒绝原因且未提交后端。"""
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


_REJECTIONS = {
    "ambiguous_action": ("swap_extract_candidates", "AmbiguousActionError"),
    "non_positive_quantity": ("swap_normalize", "NonPositiveQuantityError"),
}


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def evaluate(ctx: Any) -> EvaluationResult:
    experiment = getattr(ctx, "experiment", None)
    expected = _object(getattr(experiment, "item_expected_output", None))
    output = _object(getattr(ctx.observation, "output", None))
    expected_turns = [expected, *(expected.get("sub_scenes") or [])]
    actual_turns = output.get("turns") or [output]
    failures = []
    count = 0
    for index, turn in enumerate(expected_turns):
        kind = _object(turn).get("expected", {}).get("rejection")
        if kind is None:
            continue
        count += 1
        actual = _object(actual_turns[index]) if index < len(actual_turns) else {}
        error = _object(actual.get("error"))
        wanted = _REJECTIONS.get(kind) if isinstance(kind, str) else None
        trace = actual.get("trace") or ""
        passed = (
            wanted is not None
            and (error.get("node"), error.get("type")) == wanted
            and actual.get("api_code") is None and actual.get("api_result") is None
            and actual.get("place_params") is None
            and isinstance(trace, str) and f"{wanted[0]}[error]" in trace
            and "swap_place_order_submit" not in trace
            and bool(actual.get("reply_text"))
        )
        if not passed:
            failures.append(f"第 {index + 1} 轮未满足 {kind} 拒绝与无提交验收")
    passed = count > 0 and not failures
    return EvaluationResult(scores=[Score(
        name="det_rejection_match_pass", value=passed, data_type="BOOLEAN",
        comment=("全部拒绝原因匹配，未提交后端" if passed else
                 "；".join(failures) or "没有明确的 expected.rejection"),
        metadata={"assertion_count": count, "mismatch_count": len(failures)},
    )])
