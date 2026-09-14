"""Loader for the two active fixture dialects under tests/fixtures/categories."""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TurnSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    scene: str = ""
    send_text: str
    at_bot: bool = False
    quote_previous: bool | None = None
    expected: dict[str, Any] = Field(default_factory=dict)
    response_contains: list[str] = Field(default_factory=list)
    response_contains_any: list[str] = Field(default_factory=list)
    response_not_contains: list[str] = Field(default_factory=list)


class GoldenCase(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    category: str
    type: str = ""
    source: str = ""
    name: str = ""
    case_no: str = ""
    scene: str = ""
    turns: list[TurnSpec] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""
    source_path: str = ""
    source_line: int = 0


def _assertion_lines(value: Any, *, origin: str, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ValueError(f"{origin}: {field_name} must be a string or list[str]")


def _turn_from_object(
    obj: dict[str, Any], *, origin: str, default_at_bot: bool
) -> TurnSpec:
    send_text = obj.get("send_text")
    if not isinstance(send_text, str) or not send_text.strip():
        raise ValueError(f"{origin}: send_text is required")
    expected = obj.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"{origin}: expected must be an object")
    return TurnSpec(
        scene=str(obj.get("scene") or ""),
        send_text=send_text,
        at_bot=obj.get("at_bot", default_at_bot),
        quote_previous=obj.get("quote_previous"),
        expected=expected,
        response_contains=_assertion_lines(
            obj.get("response_contains"), origin=origin, field_name="response_contains"
        ),
        response_contains_any=_assertion_lines(
            obj.get("response_contains_any"),
            origin=origin,
            field_name="response_contains_any",
        ),
        response_not_contains=_assertion_lines(
            obj.get("response_not_contains"),
            origin=origin,
            field_name="response_not_contains",
        ),
    )


def normalize_case(obj: dict[str, Any], *, origin: str) -> GoldenCase:
    legacy = {key for key in ("conversation", "raw_content") if key in obj}
    if legacy:
        raise ValueError(f"{origin}: legacy fields are not supported: {sorted(legacy)}")

    case_id = obj.get("id") or obj.get("caseNo")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"{origin}: id or caseNo is required")
    name = str(obj.get("name") or case_id)
    case_no = str(obj.get("caseNo") or case_id)
    origin_path, _, origin_line = origin.rpartition(":")
    category = str(obj.get("category") or Path(origin_path).stem)
    expected = obj.get("expected") or {}
    if not isinstance(expected, dict):
        raise ValueError(f"{origin}: expected must be an object")

    turns = [_turn_from_object(obj, origin=origin, default_at_bot=True)]
    sub_scenes = obj.get("sub_scenes") or []
    if not isinstance(sub_scenes, list):
        raise ValueError(f"{origin}: sub_scenes must be a list")
    for index, sub_scene in enumerate(sub_scenes):
        if not isinstance(sub_scene, dict):
            raise ValueError(f"{origin}: sub_scenes[{index}] must be an object")
        turns.append(
            _turn_from_object(
                sub_scene,
                origin=f"{origin}:sub_scenes[{index}]",
                default_at_bot=False,
            )
        )

    return GoldenCase(
        id=case_id,
        category=category,
        type=str(obj.get("type") or ""),
        source=str(obj.get("source") or ""),
        name=name,
        case_no=case_no,
        scene=str(obj.get("scene") or ""),
        turns=turns,
        expected=expected,
        expected_output=str(expected.get("output") or ""),
        source_path=origin_path,
        source_line=int(origin_line),
    )


def build_overview(case: GoldenCase) -> str:
    """生成 case 概览文本（LangFuse metadata / 本地预览共用）。"""
    expected = case.expected
    lines = [
        f"ID: {case.id}",
        f"类别: {case.category}",
        f"用例类型: {case.type}",
        f"来源: {case.source}",
        f"期望路由: product_type={expected.get('product_type', '')}, intent={expected.get('intent', '')}",
        "对话:",
    ]
    for i, turn in enumerate(case.turns, 1):
        if i > 1 and turn.quote_previous is not False:
            lines.append(f"  第{i}轮: send_text={turn.send_text}; 引用上一轮机器人回复")
        else:
            lines.append(f"  第{i}轮: send_text={turn.send_text}; 无引用")
    return "\n".join(lines)


def discover_fixtures(root: Path = Path("tests/fixtures")) -> list[Path]:
    categories = root / "categories" if root.name != "categories" else root
    return sorted(categories.glob("*.jsonl"))


def load_golden(
    paths: Sequence[Path] | Path | None = None,
    *,
    root: Path = Path("tests/fixtures"),
) -> list[GoldenCase]:
    if paths is None:
        fixture_paths = discover_fixtures(root)
    else:
        raw_paths = [paths] if isinstance(paths, Path) else list(paths)
        fixture_paths: list[Path] = []
        for path in raw_paths:
            fixture_paths.extend(sorted(path.glob("*.jsonl")) if path.is_dir() else [path])

    cases: list[GoldenCase] = []
    for path in fixture_paths:
        with path.open(encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                origin = f"{path}:{line_number}"
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{origin}: invalid JSON: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ValueError(f"{origin}: case must be an object")
                cases.append(normalize_case(payload, origin=origin))
    return cases


def validate_case(case: GoldenCase, origin: str = "fixture") -> list[str]:
    errors: list[str] = []
    if not case.id.strip():
        errors.append(f"{origin}: id is empty")
    if not case.category.strip():
        errors.append(f"{origin}: category is empty")
    if not case.turns:
        errors.append(f"{origin}: turns is empty")
    return errors


def index_by_category(cases: Iterable[GoldenCase]) -> dict[str, list[GoldenCase]]:
    grouped: dict[str, list[GoldenCase]] = defaultdict(list)
    for case in cases:
        grouped[case.category].append(case)
    return dict(grouped)


def filter_by_category(
    cases: Iterable[GoldenCase], category_prefix: str | None
) -> list[GoldenCase]:
    return [
        case
        for case in cases
        if not category_prefix or case.category.startswith(category_prefix)
    ]


def filter_by_ids(cases: Iterable[GoldenCase], ids: list[str] | None) -> list[GoldenCase]:
    if not ids:
        return list(cases)
    wanted = set(ids)
    return [case for case in cases if case.id in wanted]
