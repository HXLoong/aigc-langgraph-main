#!/usr/bin/env python3
"""Validate the active fixtures: categories/*.jsonl (A dialect) + unified_golden.jsonl (B dialect).

ADR 0024 D6：两份现役数据源同受 lint；一个文件只放一种方言，id 跨文件唯一。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UNIFIED_FIXTURE_NAME = "unified_golden.jsonl"
#: 运行时 product_type 取值（app/graph/state.py ProductType）；fixture 标了别的值只告警不阻断
KNOWN_PRODUCT_TYPES = ("swap", "option", "option_close", "unknown")


def _lines(value: Any) -> list[str] | None:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    return None


def _iter_jsonl(path: Path, errors: list[str]):
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        errors.append(f"{path}: empty file")
        return
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        origin = f"{path}:{line_number}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{origin}: invalid JSON: {exc}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{origin}: case must be an object")
            continue
        yield origin, obj


#: 写类 category（下单 / 确认 / 询价建单 / 平仓）：ADR 0024 D6 要求 positive case 带
#: `expected.place_params`（从真实 HTTP payload 反向生成后人工抽检），否则评估门只靠文案。
#: 现阶段缺失记 WARNING；业务方补齐后升为 ERROR。
WRITE_CATEGORIES = frozenset({
    "swap/place_order", "swap/modify", "swap/confirm", "swap/confirm_modify",
    "option/place_order", "option/place_from_quote", "option/inquiry", "option/inquiry_place",
    "option/confirm", "option/modify_request",
    "option_close/place", "option_close/place_amend", "option_close/confirm",
})
_ORDER_LIST_KEYS = ("orderList", "closeOrderList")


def _lint_place_params(origin: str, obj: dict[str, Any], expected: dict[str, Any],
                       errors: list[str], warnings: list[str]) -> None:
    case_id = obj.get("id")
    if "place_params" in expected:
        params = expected["place_params"]
        order_list = params.get("orderList", params.get("closeOrderList")) if isinstance(params, dict) else None
        if not isinstance(params, dict) or not isinstance(order_list, list):
            errors.append(
                f"{origin}: {case_id!r} expected.place_params must be an object with {'/'.join(_ORDER_LIST_KEYS)} list"
            )
        return
    if obj.get("category") in WRITE_CATEGORIES and obj.get("type", "positive") == "positive":
        warnings.append(
            f"{origin}: {case_id!r} write-class case {obj.get('category')!r} has no expected.place_params"
            " (ADR 0024 D6; evaluation gate falls back to text only)"
        )


def validate_unified(path: Path, ids: list[str]) -> tuple[list[str], list[str]]:
    """B 方言 lint：id + conversation[].raw_content + expected{product_type, intent}；返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    for origin, obj in _iter_jsonl(path, errors):
        a_fields = sorted(key for key in ("send_text", "sub_scenes", "name") if key in obj)
        if a_fields:
            errors.append(f"{origin}: fields {a_fields} belong to the A dialect (categories/), not {path.name}")
        case_id = obj.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"{origin}: missing id")
        else:
            ids.append(case_id)
        if not isinstance(obj.get("category"), str) or not obj["category"].strip():
            errors.append(f"{origin}: missing category")
        conversation = obj.get("conversation")
        if not isinstance(conversation, list) or not conversation:
            errors.append(f"{origin}: conversation must be a non-empty list")
        else:
            for index, turn in enumerate(conversation):
                if not isinstance(turn, dict) or not isinstance(turn.get("raw_content"), str):
                    errors.append(f"{origin}: conversation[{index}] missing raw_content")
                elif not turn["raw_content"].strip():
                    warnings.append(
                        f"{origin}: {obj.get('id')!r} conversation[{index}] raw_content is empty"
                        " (unrunnable, harness skips it; Issue #113 业务方 review)"
                    )
        expected = obj.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{origin}: expected must be an object")
            continue
        for field_name in ("product_type", "intent"):
            if not isinstance(expected.get(field_name), str) or not expected[field_name].strip():
                errors.append(f"{origin}: expected.{field_name} is required")
        _lint_place_params(origin, obj, expected, errors, warnings)
        product_type = expected.get("product_type")
        if isinstance(product_type, str) and product_type not in KNOWN_PRODUCT_TYPES:
            warnings.append(
                f"{origin}: {case_id!r} expected.product_type={product_type!r} is not a runtime ProductType"
                f" {KNOWN_PRODUCT_TYPES} (Issue #113 业务方 review)"
            )
    return errors, warnings


def _unified_path(root: Path) -> Path:
    fixtures_root = root.parent if root.name == "categories" else root
    return fixtures_root / UNIFIED_FIXTURE_NAME


def collect_warnings(root: Path) -> list[str]:
    unified = _unified_path(root)
    if not unified.is_file():
        return []
    return validate_unified(unified, [])[1]


def validate(root: Path, verbose: bool = False) -> list[str]:
    categories = root / "categories" if root.name != "categories" else root
    if not categories.is_dir():
        return [f"missing fixture directory: {categories}"]
    paths = sorted(categories.glob("*.jsonl"))
    if not paths:
        return [f"no JSONL fixtures found: {categories}"]

    errors: list[str] = []
    ids: list[str] = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            errors.append(f"{path}: empty file")
            continue
        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            origin = f"{path}:{line_number}"
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{origin}: invalid JSON: {exc}")
                continue
            if not isinstance(obj, dict):
                errors.append(f"{origin}: case must be an object")
                continue
            b_fields = sorted(key for key in ("conversation", "raw_content") if key in obj)
            if b_fields:
                errors.append(
                    f"{origin}: fields {b_fields} belong to the B dialect ({UNIFIED_FIXTURE_NAME}), not categories/"
                )
            case_id = obj.get("id") or obj.get("caseNo")
            if not isinstance(case_id, str) or not case_id.strip():
                errors.append(f"{origin}: missing id/caseNo")
            else:
                ids.append(case_id)
            if not isinstance(obj.get("name", obj.get("caseNo")), str):
                errors.append(f"{origin}: missing name/caseNo")
            if not isinstance(obj.get("send_text"), str) or not obj["send_text"].strip():
                errors.append(f"{origin}: missing send_text")
            category = str(obj.get("category") or path.stem)
            if not category.startswith(("swap", "option", "option_close")):
                errors.append(f"{origin}: invalid category {category!r}")
            for field_name in ("response_contains", "response_contains_any", "response_not_contains"):
                if field_name in obj and _lines(obj[field_name]) is None:
                    errors.append(f"{origin}: {field_name} must be string or list[str]")
            sub_scenes = obj.get("sub_scenes", [])
            if not isinstance(sub_scenes, list):
                errors.append(f"{origin}: sub_scenes must be a list")
            else:
                for index, sub_scene in enumerate(sub_scenes):
                    if not isinstance(sub_scene, dict) or not isinstance(sub_scene.get("send_text"), str) or not sub_scene["send_text"].strip():
                        errors.append(f"{origin}: sub_scenes[{index}] missing send_text")
    unified = _unified_path(root)
    warnings: list[str] = []
    if unified.is_file():
        unified_errors, warnings = validate_unified(unified, ids)
        errors.extend(unified_errors)
        paths.append(unified)
    for duplicate, count in Counter(ids).items():
        if count > 1:
            errors.append(f"duplicate id {duplicate!r}: {count} occurrences")
    if verbose:
        print(f"validated {len(paths)} fixture files and {len(ids)} cases")
        missing_params = sum("expected.place_params" in warning for warning in warnings)
        if missing_params:
            print(f"write-class cases without expected.place_params: {missing_params} (ADR 0024 D6)")
        for warning in warnings:
            print(f"WARNING: {warning}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT / "tests" / "fixtures")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    errors = validate(args.root, args.verbose)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 2 if any(error.startswith("missing fixture") or error.startswith("no JSONL") for error in errors) else 1
    print("fixture consistency: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
