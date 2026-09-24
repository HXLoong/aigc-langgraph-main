"""Langfuse Code Evaluator：意图集逐轮比对 expected.product_type / intent。

与 response_* 评估器同构：expectedOutput 保持 biz 结构（首轮 + sub_scenes[]），
实际值取 Experiment Item 根输出的 turns[i].product_type / intent。只比对 expected 里
出现的键（product_type=unknown 的反案例可以不标 intent）；没有任何可比对键视为失败，
避免标注缺失被当作通过。上传到 Langfuse 后独立执行，因此不 import harness 其它模块。
"""

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


_INTENT_KEYS = ("product_type", "intent")


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


def _expected_intent(turn: Any) -> dict[str, str]:
    """取一轮 expected 里的 product_type / intent（只保留非空字符串）。"""
    if not isinstance(turn, dict):
        return {}
    expected = turn.get("expected")
    if not isinstance(expected, dict):
        return {}
    return {
        key: expected[key].strip()
        for key in _INTENT_KEYS
        if isinstance(expected.get(key), str) and expected[key].strip()
    }


def _actual_value(turn: Any, key: str) -> str:
    if not isinstance(turn, dict):
        return ""
    value = turn.get(key)
    return "" if value is None else str(value)


def evaluate(ctx: Any) -> EvaluationResult:
    """对 Experiment Item 的每轮路由结果生成一个 Boolean Score。"""
    experiment = getattr(ctx, "experiment", None)
    expected_output = _json_object(
        getattr(experiment, "item_expected_output", None) if experiment else None
    )
    output = _json_object(getattr(ctx.observation, "output", None))

    expected_turns: list[Any] = [expected_output]
    sub_scenes = expected_output.get("sub_scenes")
    if isinstance(sub_scenes, list):
        expected_turns.extend(sub_scenes)

    actual_turns = output.get("turns")
    if not isinstance(actual_turns, list):
        actual_turns = [output]

    mismatches: list[str] = []
    assertion_count = 0
    for index, expected_turn in enumerate(expected_turns):
        wanted = _expected_intent(expected_turn)
        if not wanted:
            continue
        assertion_count += len(wanted)
        if index >= len(actual_turns):
            mismatches.append(f"第 {index + 1} 轮无实际输出（早停或未执行），期望 {wanted}")
            continue
        actual_turn = actual_turns[index]
        for key, expected_value in wanted.items():
            actual_value = _actual_value(actual_turn, key)
            if actual_value != expected_value:
                mismatches.append(
                    f"第 {index + 1} 轮 {key} 不符：期望 {expected_value}，"
                    f"实际 {actual_value or '(空)'}"
                )

    if assertion_count == 0:
        return EvaluationResult(
            scores=[
                Score(
                    name="det_intent_match_pass",
                    value=False,
                    data_type="BOOLEAN",
                    comment="没有可比对的 expected.product_type / intent；意图集用例必须逐轮标注",
                    metadata={"assertion_count": 0, "mismatch_count": 0},
                )
            ]
        )

    passed = not mismatches
    return EvaluationResult(
        scores=[
            Score(
                name="det_intent_match_pass",
                value=passed,
                data_type="BOOLEAN",
                comment="全部轮次路由与意图均匹配" if passed else "；".join(mismatches),
                metadata={
                    "assertion_count": assertion_count,
                    "mismatch_count": len(mismatches),
                },
            )
        ]
    )
