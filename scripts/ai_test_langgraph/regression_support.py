"""Shared, dependency-free helpers for the LangGraph regression workbench."""

from __future__ import annotations

import json
import os
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BOT_NAME = "A股场外交易助手"
DEFAULT_GUID = ""
DEFAULT_OPTION_COUNTERPARTIES: list[dict[str, Any]] = []
DEFAULT_SWAP_COUNTERPARTIES: list[dict[str, Any]] = []


class RunnerError(RuntimeError):
    """Raised when regression configuration or fixture data is invalid."""


@dataclass
class AssertionResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def parse_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    quote_character = ""
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote_character:
            if character == "\\" and quote_character == '"':
                escaped = True
            elif character == quote_character:
                quote_character = ""
            continue
        if character in {"'", '"'}:
            quote_character = character
        elif character == "#" and (index == 0 or value[index - 1].isspace()):
            value = value[:index].rstrip()
            break
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip():
            values[key.strip()] = parse_dotenv_value(value)
    return values


def env_value(env: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = (os.environ.get(name) or env.get(name) or "").strip()
        if value:
            return value
    return default


def require_config(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise RunnerError(f"缺少有效配置：{label}")
    return value


def parse_json_env(
    value: str,
    default: Sequence[dict[str, Any]],
    label: str,
) -> str:
    if not value:
        return json.dumps(list(default), ensure_ascii=False)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RunnerError(f"{label} 不是合法 JSON：{exc}") from exc
    if not isinstance(parsed, list):
        raise RunnerError(f"{label} 必须是 JSON 数组")
    return json.dumps(parsed, ensure_ascii=False)


def _expected_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(line).strip() for line in value if str(line).strip()]
    return [str(value).strip()]


def evaluate_response(
    answer: str,
    scenario: dict[str, Any],
    *,
    ignore_leading_mentions: bool = True,
    outputs: dict[str, Any] | None = None,
) -> AssertionResult:
    del ignore_leading_mentions
    failures: list[str] = []
    for line in _expected_lines(scenario.get("response_contains")):
        if line not in answer:
            failures.append(f"内容包含失败：未找到 {line!r}")
    for line in _expected_lines(scenario.get("response_contains_any")):
        if line not in answer:
            failures.append(f"内容包含失败：未找到 {line!r}")
    for line in _expected_lines(scenario.get("response_not_contains")):
        if line in answer:
            failures.append(f"禁止包含失败：实际出现 {line!r}")
    expected = scenario.get("expected")
    if isinstance(expected, dict) and outputs is not None:
        for field_name in ("product_type", "intent"):
            expected_value = expected.get(field_name)
            if expected_value is not None and outputs.get(field_name) != expected_value:
                failures.append(
                    f"{field_name} 断言失败：期望 {expected_value!r}，"
                    f"实际 {outputs.get(field_name)!r}"
                )
        expected_winners = expected.get("winners")
        if expected_winners is None and "winner" in expected:
            expected_winners = [expected["winner"]] if expected["winner"] else []
        if expected_winners is not None:
            actual_winners = [
                ticker.get("windCode")
                for ticker in outputs.get("tickers", [])
                if isinstance(ticker, dict) and ticker.get("windCode")
            ]
            if actual_winners != expected_winners:
                failures.append(
                    f"ticker 断言失败：期望 {expected_winners!r}，实际 {actual_winners!r}"
                )
        if "needs_hitl" in expected:
            actual_hitl = bool(outputs.get("ticker_hitl_candidates"))
            if actual_hitl != bool(expected["needs_hitl"]):
                failures.append(
                    f"needs_hitl 断言失败：期望 {bool(expected['needs_hitl'])!r}，"
                    f"实际 {actual_hitl!r}"
                )
    return AssertionResult(passed=not failures, failures=failures)


def _fixture_case(case: dict[str, Any], path: Path, line_number: int) -> dict[str, Any]:
    if case.get("name") and case.get("send_text"):
        converted = dict(case)
    elif isinstance(case.get("conversation"), list) and case.get("id"):
        turns = case["conversation"]
        if not turns or not isinstance(turns[0], dict) or not turns[0].get("raw_content"):
            raise RunnerError(f"{path}:{line_number} conversation 缺少 raw_content")
        converted = {
            "name": str(case["id"]),
            "caseNo": str(case["id"]),
            "category": case.get("category"),
            "type": case.get("type"),
            "source": case.get("source"),
            "scene": str(case.get("category") or "主场景"),
            "send_text": str(turns[0]["raw_content"]),
            "sub_scenes": [
                {
                    "scene": f"第 {index} 轮",
                    "send_text": str(turn.get("raw_content") or ""),
                    "at_bot": False,
                    "quote_previous": bool(turn.get("quote_desc")),
                }
                for index, turn in enumerate(turns[1:], 2)
                if isinstance(turn, dict) and turn.get("raw_content")
            ],
            "expected": case.get("expected", {}),
        }
    elif case.get("id") and "raw_content" in case:
        converted = {
            "name": str(case["id"]),
            "caseNo": str(case["id"]),
            "category": case.get("category"),
            "type": case.get("type"),
            "source": case.get("source"),
            "scene": str(case.get("category") or "Ticker 场景"),
            "send_text": str(case["raw_content"]),
            "expected": case.get("expected", {}),
        }
    else:
        raise RunnerError(
            f"{path}:{line_number} 不是支持的 LangGraph fixture 或回归用例格式"
        )
    converted["_source"] = str(path)
    converted["_source_index"] = line_number
    return converted


def load_cases(paths: Sequence[Path]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".jsonl":
            raise RunnerError(f"数据文件必须是存在的 .jsonl 文件：{path}")
        file_count = 0
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise RunnerError(
                    f"JSONL 解析失败 {path}:{line_number}：{exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise RunnerError(f"{path}:{line_number} 用例必须是 JSON 对象")
            cases.append(_fixture_case(value, path, line_number))
            file_count += 1
        if not file_count:
            raise RunnerError(f"JSONL 数据文件没有有效用例：{path}")
    return cases


def select_cases(
    cases: Sequence[dict[str, Any]],
    *,
    names: Sequence[str],
    case_nos: Sequence[str],
    keyword: str,
    limit: int | None,
    shuffle: bool,
    seed: int,
) -> list[dict[str, Any]]:
    if limit is not None and limit < 1:
        raise RunnerError("--limit 必须大于 0")
    name_set = set(names)
    case_no_set = set(case_nos)
    selected = [
        case
        for case in cases
        if (not name_set or str(case.get("name")) in name_set)
        and (not case_no_set or str(case.get("caseNo")) in case_no_set)
        and (not keyword or keyword in json.dumps(case, ensure_ascii=False))
    ]
    if shuffle:
        random.Random(seed).shuffle(selected)
    return selected[:limit] if limit is not None else selected
