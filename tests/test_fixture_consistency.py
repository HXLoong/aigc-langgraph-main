"""基准迁移检查必须检测数据丢失、空文件和重复编号。"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import check_fixture_consistency as checker


def _valid_case(**overrides: object) -> dict:
    case: dict = {
        "id": "case-001",
        "name": "case-001",
        "category": "option/inquiry",
        "send_text": "600519.SH，欧式看涨，1M",
        "expected": {"product_type": "option"},
    }
    case.update(overrides)
    return case


def _validate(root: Path, payloads: list[dict]) -> list[str]:
    categories = root / "categories"
    categories.mkdir(exist_ok=True)
    lines = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    (categories / "option.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return checker.validate(root)


def test_valid_case_passes(tmp_path: Path) -> None:
    assert _validate(tmp_path, [_valid_case()]) == []


def test_legacy_fields_rejected(tmp_path: Path) -> None:
    case = _valid_case()
    case["conversation"] = [{"raw_content": "x"}]
    case["raw_content"] = "x"
    errors = _validate(tmp_path, [case])
    assert any("legacy fields" in error for error in errors)


def test_duplicate_and_missing_ids_rejected(tmp_path: Path) -> None:
    errors = _validate(tmp_path, [_valid_case(), _valid_case()])
    assert any("duplicate id" in error for error in errors)
    errors = _validate(tmp_path, [_valid_case(id="")])
    assert any("missing id/caseNo" in error for error in errors)


def test_invalid_category_and_wrong_assertion_types_rejected(tmp_path: Path) -> None:
    errors = _validate(
        tmp_path,
        [_valid_case(category="unknown", response_contains=[1, 2])],
    )
    assert any("invalid category" in error for error in errors)
    assert any("response_contains must be string or list[str]" in error for error in errors)


def test_empty_fixture_file_rejected(tmp_path: Path) -> None:
    categories = tmp_path / "categories"
    categories.mkdir()
    (categories / "option.jsonl").write_text("", encoding="utf-8")
    assert any("empty file" in error for error in checker.validate(tmp_path))
