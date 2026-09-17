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


def test_b_dialect_fields_rejected_in_categories(tmp_path: Path) -> None:
    """categories/ 只放 A 方言；conversation / raw_content 属于 unified_golden.jsonl（B 方言）。"""
    case = _valid_case()
    case["conversation"] = [{"raw_content": "x"}]
    case["raw_content"] = "x"
    errors = _validate(tmp_path, [case])
    assert any("belong to the B dialect" in error for error in errors)


def _b_case(**overrides: object) -> dict:
    case: dict = {
        "id": "opt-001",
        "category": "option/inquiry",
        "type": "positive",
        "source": "business_seed",
        "expected": {"product_type": "option", "intent": "new_inquiry", "output": "报价卡"},
        "conversation": [{"raw_content": "600519.SH，欧式看涨，1M", "quote_desc": ""}],
    }
    case.update(overrides)
    return case


def _write_unified(root: Path, payloads: list[dict]) -> None:
    lines = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    (root / "unified_golden.jsonl").write_text("\n".join(lines), encoding="utf-8")


def test_unified_b_dialect_file_is_linted(tmp_path: Path) -> None:
    """ADR 0024 D6：unified_golden.jsonl 并入现役数据源后同受 lint 守护。"""
    _write_unified(tmp_path, [_b_case()])
    assert _validate(tmp_path, [_valid_case()]) == []

    _write_unified(tmp_path, [_b_case(conversation=[{"quote_desc": "引用"}])])
    errors = _validate(tmp_path, [_valid_case()])
    assert any("unified_golden.jsonl:1" in error and "raw_content" in error for error in errors)

    _write_unified(tmp_path, [_b_case(expected={"product_type": "option"})])
    errors = _validate(tmp_path, [_valid_case()])
    assert any("expected.intent" in error for error in errors)

    _write_unified(tmp_path, [_b_case(send_text="A 方言字段")])
    errors = _validate(tmp_path, [_valid_case()])
    assert any("send_text" in error and "A dialect" in error for error in errors)


def test_ids_must_be_unique_across_categories_and_unified(tmp_path: Path) -> None:
    _write_unified(tmp_path, [_b_case(id="case-001")])
    errors = _validate(tmp_path, [_valid_case(id="case-001")])
    assert any("duplicate id 'case-001'" in error for error in errors)


def test_unknown_product_type_in_unified_is_a_warning_not_an_error(tmp_path: Path) -> None:
    """9 条 query/* 记录标了运行时不存在的 product_type=query（Issue #113 业务方 review 项）：
    schema 合法故不阻断，但要能被列出来。"""
    _write_unified(tmp_path, [_b_case(id="query-001", category="query/trs", expected={
        "product_type": "query", "intent": "query_order_status", "output": ""})])
    assert _validate(tmp_path, [_valid_case()]) == []
    warnings = checker.collect_warnings(tmp_path)
    assert warnings and "query-001" in warnings[0] and "product_type" in warnings[0]


def test_empty_raw_content_in_unified_is_a_warning_not_an_error(tmp_path: Path) -> None:
    """键在但为空 = 数据缺陷（harness 标 skip_reason 跳过）；键缺失才是 schema 错误。"""
    _write_unified(tmp_path, [_b_case(conversation=[{"raw_content": "我想平仓"}, {"raw_content": "", "quote_desc": "引用"}])])
    assert _validate(tmp_path, [_valid_case()]) == []
    warnings = checker.collect_warnings(tmp_path)
    assert any("conversation[1] raw_content is empty" in warning for warning in warnings)


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
