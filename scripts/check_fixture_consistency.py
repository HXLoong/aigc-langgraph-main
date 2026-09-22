#!/usr/bin/env python3
"""Validate the active fixtures: categories/*.jsonl (A dialect) + unified_golden.jsonl (B dialect)
+ intent/*.jsonl (意图集，A 方言子集).

ADR 0024 D6：现役数据源同受 lint；一个文件只放一种方言，id 跨文件唯一。
意图集（tests/fixtures/intent/）只评路由与意图：逐轮必须标 expected.product_type / intent
且取运行时枚举值，禁止出现卡片文本断言（那是 categories/ 业务集的职责）。
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
#: 意图集目录（与 categories/ 平级）；文件按产品命名，id 以 intent- 开头
INTENT_DIR_NAME = "intent"
INTENT_ID_PREFIX = "intent-"
INTENT_CASE_TYPES = ("positive", "negative")
INTENT_PRODUCTS = ("swap", "option", "option_close")
TEXT_ASSERTION_FIELDS = ("response_contains", "response_contains_any", "response_not_contains")


def intent_types_by_product() -> dict[str, tuple[str, ...]]:
    """运行时意图枚举（唯一真源是各子图 models.py 的 Literal，不在此复制）。"""
    from typing import get_args

    from app.subgraphs.close.models import CloseIntentType
    from app.subgraphs.option.models import OptionIntentType
    from app.subgraphs.swap.models import SwapIntentType

    return {
        "swap": tuple(get_args(SwapIntentType)),
        "option": tuple(get_args(OptionIntentType)),
        "option_close": tuple(get_args(CloseIntentType)),
        # 一级路由落 unknown 时不进子图，运行时 intent 为空：反案例不标 intent
        "unknown": (),
    }


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
        product_type = expected.get("product_type")
        if isinstance(product_type, str) and product_type not in KNOWN_PRODUCT_TYPES:
            warnings.append(
                f"{origin}: {case_id!r} expected.product_type={product_type!r} is not a runtime ProductType"
                f" {KNOWN_PRODUCT_TYPES} (Issue #113 业务方 review)"
            )
    return errors, warnings


def _check_intent_turn(origin: str, turn: dict[str, Any], intents: dict[str, tuple[str, ...]]) -> list[str]:
    """一轮意图集断言：只允许 expected.product_type / intent，值取运行时枚举。"""
    errors: list[str] = []
    for field_name in TEXT_ASSERTION_FIELDS:
        if field_name in turn:
            errors.append(
                f"{origin}: {field_name} belongs to the business suite (categories/), not {INTENT_DIR_NAME}/"
            )
    expected = turn.get("expected")
    if not isinstance(expected, dict):
        errors.append(f"{origin}: expected.product_type is required")
        errors.append(f"{origin}: expected.intent is required")
        return errors
    product_type = expected.get("product_type")
    if not isinstance(product_type, str) or not product_type.strip():
        errors.append(f"{origin}: expected.product_type is required")
        return errors
    if product_type not in intents:
        errors.append(
            f"{origin}: product_type {product_type!r} is not a runtime ProductType {KNOWN_PRODUCT_TYPES}"
        )
        return errors
    intent = expected.get("intent")
    if product_type == "unknown":
        if intent is not None:
            errors.append(f"{origin}: product_type 'unknown' has no subgraph intent; drop expected.intent")
        return errors
    if not isinstance(intent, str) or not intent.strip():
        errors.append(f"{origin}: expected.intent is required")
    elif intent not in intents[product_type]:
        errors.append(
            f"{origin}: intent {intent!r} is not a {product_type} intent {intents[product_type]}"
        )
    return errors


def validate_intent(path: Path, ids: list[str]) -> list[str]:
    """意图集 lint：A 方言子集 + 逐轮 expected + 命名约定；返回 errors。"""
    errors: list[str] = []
    intents = intent_types_by_product()
    for origin, obj in _iter_jsonl(path, errors):
        b_fields = sorted(key for key in ("conversation", "raw_content") if key in obj)
        if b_fields:
            errors.append(f"{origin}: fields {b_fields} belong to the B dialect, not {INTENT_DIR_NAME}/")
        case_id = obj.get("id") or obj.get("caseNo")
        if not isinstance(case_id, str) or not case_id.strip():
            errors.append(f"{origin}: missing id/caseNo")
        else:
            ids.append(case_id)
            if not case_id.startswith(INTENT_ID_PREFIX):
                errors.append(f"{origin}: id must start with {INTENT_ID_PREFIX!r}: {case_id!r}")
        if not isinstance(obj.get("name", obj.get("caseNo")), str):
            errors.append(f"{origin}: missing name/caseNo")
        category = obj.get("category")
        if not isinstance(category, str) or category not in {
            f"{INTENT_DIR_NAME}/{product}" for product in INTENT_PRODUCTS
        }:
            errors.append(
                f"{origin}: category must be '{INTENT_DIR_NAME}/<product>' with product in {INTENT_PRODUCTS}: {category!r}"
            )
        if obj.get("type") not in INTENT_CASE_TYPES:
            errors.append(f"{origin}: type must be positive or negative: {obj.get('type')!r}")
        if not isinstance(obj.get("send_text"), str) or not obj["send_text"].strip():
            errors.append(f"{origin}: missing send_text")
        errors.extend(_check_intent_turn(origin, obj, intents))
        sub_scenes = obj.get("sub_scenes", [])
        if not isinstance(sub_scenes, list):
            errors.append(f"{origin}: sub_scenes must be a list")
            continue
        for index, sub_scene in enumerate(sub_scenes):
            sub_origin = f"{origin}: sub_scenes[{index}]"
            if not isinstance(sub_scene, dict):
                errors.append(f"{sub_origin} must be an object")
                continue
            if not isinstance(sub_scene.get("send_text"), str) or not sub_scene["send_text"].strip():
                errors.append(f"{sub_origin} missing send_text")
            errors.extend(_check_intent_turn(sub_origin, sub_scene, intents))
    return errors


def _intent_paths(root: Path) -> list[Path]:
    fixtures_root = root.parent if root.name == "categories" else root
    intent_dir = fixtures_root / INTENT_DIR_NAME
    return sorted(intent_dir.glob("*.jsonl")) if intent_dir.is_dir() else []


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
    for intent_path in _intent_paths(root):
        errors.extend(validate_intent(intent_path, ids))
        paths.append(intent_path)
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
