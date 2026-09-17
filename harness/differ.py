"""Deterministic assertions for normalized golden turns."""
from __future__ import annotations

from collections.abc import Collection
from typing import Any

from pydantic import BaseModel, ConfigDict

from harness.golden import TurnSpec


class FieldDiff(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str
    expected: Any = None
    actual: Any = None


ASSERT_EXCLUDED_KEYS = frozenset({"output"})


def diff_fields(
    expected: dict[str, Any] | None,
    actual: dict[str, Any] | None,
    prefix: str = "",
    exclude: Collection[str] = ASSERT_EXCLUDED_KEYS,
) -> list[FieldDiff]:
    if expected is None:
        return []
    actual = actual or {}
    diffs: list[FieldDiff] = []
    for key, expected_value in expected.items():
        if key in exclude:
            continue
        path = f"{prefix}.{key}" if prefix else key
        actual_value = actual.get(key)
        if isinstance(expected_value, dict) and isinstance(actual_value, dict):
            diffs.extend(diff_fields(expected_value, actual_value, path, exclude))
        elif isinstance(expected_value, list) and isinstance(actual_value, list):
            if len(expected_value) != len(actual_value):
                diffs.append(FieldDiff(path=f"{path}.length", expected=len(expected_value), actual=len(actual_value)))
            for index, (expected_item, actual_item) in enumerate(
                zip(expected_value, actual_value, strict=False)
            ):
                item_path = f"{path}[{index}]"
                if isinstance(expected_item, dict) and isinstance(actual_item, dict):
                    diffs.extend(diff_fields(expected_item, actual_item, item_path, exclude))
                elif expected_item != actual_item:
                    diffs.append(FieldDiff(path=item_path, expected=expected_item, actual=actual_item))
        elif expected_value != actual_value:
            diffs.append(FieldDiff(path=path, expected=expected_value, actual=actual_value))
    return diffs


def check_text_assertions(
    reply_text: str, spec: TurnSpec, *, allow_dry_run: bool = False
) -> list[FieldDiff]:
    """文本断言；`allow_dry_run=True`（harness --backend dry-run）时 DRY-RUN 标记不算失败。"""
    failures: list[FieldDiff] = []
    for expected in spec.response_contains:
        if expected not in reply_text:
            failures.append(FieldDiff(path="response_contains", expected=expected, actual=reply_text))
    if spec.response_contains_any and not any(item in reply_text for item in spec.response_contains_any):
        failures.append(
            FieldDiff(path="response_contains_any", expected=spec.response_contains_any, actual=reply_text)
        )
    for forbidden in spec.response_not_contains:
        if forbidden in reply_text:
            failures.append(FieldDiff(path="response_not_contains", expected=forbidden, actual=reply_text))
    if "DRY-RUN-" in reply_text and not allow_dry_run:
        failures.append(FieldDiff(path="runtime", expected="real backend result", actual="dry-run interception"))
    return failures


def check_structured_assertions(
    outputs: dict[str, Any], expected: dict[str, Any]
) -> list[FieldDiff]:
    """逐键比对 expected；`winners` 映射到 outputs.tickers[].windCode 做集合比较。

    HTTP outputs 的 tickers 由 TickerCandidate.model_dump()（WireModel 默认 by_alias）产出，
    键是协议 alias `windCode`，不是 Python 字段名 `wind_code`（ADR 0024 阶段 0 修正）。
    """
    remaining = dict(expected)
    winners = remaining.pop("winners", None)
    diffs = diff_fields(remaining, outputs)
    if winners is not None:
        actual = sorted(str(t.get("windCode")) for t in outputs.get("tickers") or [])
        if set(winners) != set(actual):
            diffs.append(FieldDiff(path="winners", expected=sorted(winners), actual=actual))
    return diffs


def check_case_assertions(
    turn_outputs: list[dict[str, Any]], expected: dict[str, Any]
) -> list[FieldDiff]:
    """case 级 any_turn 断言（多轮 B 方言）：任一已执行轮同时命中 expected 的全部结构化键即通过。

    只比较 `output` 之外的键；失败时把每轮的对应实际值列出来便于定位焦点轮。
    """
    wanted = {k: v for k, v in expected.items() if k not in ASSERT_EXCLUDED_KEYS}
    if not wanted:
        return []
    for outputs in turn_outputs:
        if not check_structured_assertions(outputs, wanted):
            return []
    actual = [{key: outputs.get(key) for key in wanted} for outputs in turn_outputs]
    return [FieldDiff(path="case.expected", expected=wanted, actual=actual)]


def is_pass(diffs: list[FieldDiff]) -> bool:
    return not diffs
