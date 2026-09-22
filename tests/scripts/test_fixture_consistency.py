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


# ============================================================
# ADR 0024 D6：写类 case 必须有 expected.place_params（先 WARNING，补齐后升 ERROR）
# ============================================================


def _warnings(root: Path, payloads: list[dict]) -> list[str]:
    _write_unified(root, payloads)
    assert _validate(root, [_valid_case()]) == []
    return checker.collect_warnings(root)


def test_positive_write_case_without_place_params_is_a_warning(tmp_path: Path) -> None:
    case = _b_case(id="swap-w-1", category="swap/place_order",
                   expected={"product_type": "swap", "intent": "place_order_request", "output": "卡"})
    warnings = _warnings(tmp_path, [case])
    assert any("swap-w-1" in w and "expected.place_params" in w for w in warnings), warnings


def test_negative_or_read_case_does_not_require_place_params(tmp_path: Path) -> None:
    negative = _b_case(id="swap-n-1", category="swap/place_order", type="negative",
                       expected={"product_type": "swap", "intent": "place_order_request", "output": "缺参数"})
    query = _b_case(id="swap-q-1", category="swap/query",
                    expected={"product_type": "swap", "intent": "query_order", "output": "列表"})
    assert not any("expected.place_params" in w for w in _warnings(tmp_path, [negative, query]))


def test_place_params_must_be_an_object_with_order_list(tmp_path: Path) -> None:
    bad = _b_case(id="swap-w-2", category="swap/place_order",
                  expected={"product_type": "swap", "intent": "place_order_request", "output": "卡",
                            "place_params": ["not-an-object"]})
    _write_unified(tmp_path, [bad])
    errors = _validate(tmp_path, [_valid_case()])
    assert any("swap-w-2" in e and "place_params" in e for e in errors), errors


def test_well_formed_place_params_passes_silently(tmp_path: Path) -> None:
    good = _b_case(id="swap-w-3", category="swap/place_order",
                   expected={"product_type": "swap", "intent": "place_order_request", "output": "卡",
                             "place_params": {"orderList": [{"placeOrderWindCode": "600519.SH"}]}})
    assert not any("swap-w-3" in w for w in _warnings(tmp_path, [good]))
