#!/usr/bin/env python3
"""Validate the active categories fixture directory."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _lines(value: Any) -> list[str] | None:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    return None


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
            legacy = {key for key in ("conversation", "raw_content") if key in obj}
            if legacy:
                errors.append(f"{origin}: legacy fields: {sorted(legacy)}")
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
    for duplicate, count in Counter(ids).items():
        if count > 1:
            errors.append(f"duplicate id {duplicate!r}: {count} occurrences")
    if verbose:
        print(f"validated {len(paths)} fixture files and {len(ids)} cases")
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
