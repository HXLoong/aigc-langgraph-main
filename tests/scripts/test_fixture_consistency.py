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


def test_quote_reference_shape_is_checked_without_live_quote(tmp_path: Path) -> None:
    case = _valid_case(expected={"confirm": {"orderList": [{
        "orderId": {"$ref": "quote.order_id"},
    }]}})
    assert _validate(tmp_path, [case]) == []
    case["expected"]["confirm"]["orderList"][0]["orderId"] = {"$ref": "outputs.orderId"}
    errors = _validate(tmp_path, [case])
    assert any("$ref" in error and "confirm.orderList[0].orderId" in error for error in errors)


def test_subscene_reference_selector_is_validated(tmp_path: Path) -> None:
    case = _valid_case(sub_scenes=[{"send_text": "选第二笔", "expected": {"place_params": {
        "orderList": [{"orderId": {"$ref": "quote.order_id", "position": 0}}],
    }}}])
    errors = _validate(tmp_path, [case])
    assert any("sub_scenes[0]" in error and "$ref" in error for error in errors)


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


# ── 意图集（tests/fixtures/intent/）────────────────────────────────────────


def _intent_case(**overrides: object) -> dict:
    case: dict = {
        "caseNo": "intent-option_close-001",
        "name": "查持仓后确认平仓",
        "category": "intent/option_close",
        "type": "positive",
        "send_text": "我想平仓",
        "at_bot": True,
        "expected": {"product_type": "option_close", "intent": "close_order_query"},
        "sub_scenes": [
            {
                "send_text": "确认平仓",
                "at_bot": False,
                "quote_content": "以下平仓申请，请核对详情后确认：单号：CO-20260506-DEAF117C 请引用本消息回复【确认平仓】",
                "prev_product_type": "option_close",
                "expected": {"product_type": "option_close", "intent": "close_order_confirm"},
            }
        ],
    }
    case.update(overrides)
    return case


def _validate_intent(root: Path, payloads: list[dict], *, categories: list[dict] | None = None) -> list[str]:
    (root / "categories").mkdir(exist_ok=True)
    category_lines = [json.dumps(payload, ensure_ascii=False) for payload in (categories or [_valid_case()])]
    (root / "categories" / "option.jsonl").write_text("\n".join(category_lines), encoding="utf-8")
    intent_dir = root / "intent"
    intent_dir.mkdir(exist_ok=True)
    lines = [json.dumps(payload, ensure_ascii=False) for payload in payloads]
    (intent_dir / "option_close.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return checker.validate(root)


def test_intent_fixture_dir_is_optional(tmp_path: Path) -> None:
    assert _validate(tmp_path, [_valid_case()]) == []


def test_valid_intent_case_passes(tmp_path: Path) -> None:
    assert _validate_intent(tmp_path, [_intent_case()]) == []


def test_intent_case_rejects_text_assertions(tmp_path: Path) -> None:
    """意图集只评路由与意图；卡片文本断言属于业务集。"""
    case = _intent_case(response_contains=["场外期权平仓"])
    case["sub_scenes"][0]["response_not_contains"] = ["互换订单"]
    errors = _validate_intent(tmp_path, [case])
    assert any("response_contains" in error and "business suite" in error for error in errors)
    assert any("sub_scenes[0]" in error and "response_not_contains" in error for error in errors)


def test_intent_case_requires_expected_on_every_turn(tmp_path: Path) -> None:
    case = _intent_case()
    case["sub_scenes"][0].pop("expected")
    errors = _validate_intent(tmp_path, [case])
    assert any("sub_scenes[0]" in error and "expected.intent is required" in error for error in errors)

    case = _intent_case(expected={"product_type": "option_close"})
    errors = _validate_intent(tmp_path, [case])
    assert any("expected.intent is required" in error for error in errors)


def test_intent_case_rejects_intent_outside_product_enum(tmp_path: Path) -> None:
    case = _intent_case(expected={"product_type": "swap", "intent": "new_inquiry"})
    errors = _validate_intent(tmp_path, [case])
    assert any("intent 'new_inquiry' is not a swap intent" in error for error in errors)

    case = _intent_case(expected={"product_type": "query", "intent": "close_order_query"})
    errors = _validate_intent(tmp_path, [case])
    assert any("product_type 'query' is not a runtime ProductType" in error for error in errors)


def test_intent_negative_case_may_omit_intent_for_unknown_product(tmp_path: Path) -> None:
    case = _intent_case(
        caseNo="intent-option_close-002",
        type="negative",
        send_text="今天天气不错",
        expected={"product_type": "unknown"},
        sub_scenes=[],
    )
    assert _validate_intent(tmp_path, [case]) == []


def test_intent_case_naming_and_type_rules(tmp_path: Path) -> None:
    errors = _validate_intent(tmp_path, [_intent_case(caseNo="case-030")])
    assert any("id must start with 'intent-'" in error for error in errors)

    errors = _validate_intent(tmp_path, [_intent_case(category="option_close/place")])
    assert any("category must be 'intent/<product>'" in error for error in errors)

    errors = _validate_intent(tmp_path, [_intent_case(type="smoke")])
    assert any("type must be positive or negative" in error for error in errors)


def test_intent_ids_must_be_unique_across_categories(tmp_path: Path) -> None:
    errors = _validate_intent(
        tmp_path,
        [_intent_case(caseNo="intent-shared")],
        categories=[_valid_case(id="intent-shared")],
    )
    assert any("duplicate id 'intent-shared'" in error for error in errors)


# ── 意图集 · 标的识别（expected.instruments）────────────────────────────────


def _instrument_case(instruments: object) -> dict:
    case = _intent_case(
        caseNo="intent-swap-instrument-001",
        category="intent/swap",
        send_text="港股市价买一百万京东",
        expected={
            "product_type": "swap",
            "intent": "place_order_request",
            "instruments": instruments,
        },
        sub_scenes=[],
    )
    return case


def test_intent_case_accepts_instruments_with_expression_and_market_candidates(tmp_path: Path) -> None:
    case = _instrument_case(
        [{"expression": ["京东"], "transaction_type": ["HK_STOCK", "SH_HK_CONNECT"]}, {"expression": "300748.sz"}]
    )
    assert _validate_intent(tmp_path, [case]) == []


def test_intent_case_rejects_malformed_instruments(tmp_path: Path) -> None:
    errors = _validate_intent(tmp_path, [_instrument_case([])])
    assert any("expected.instruments must be a non-empty list" in error for error in errors)

    errors = _validate_intent(tmp_path, [_instrument_case([{"expression": ""}])])
    assert any("instruments[0].expression" in error for error in errors)

    errors = _validate_intent(tmp_path, [_instrument_case([{"expression": "京东", "transaction_type": "HK"}])])
    assert any("instruments[0].transaction_type 'HK' is not a SwapTransactionType" in error for error in errors)

    errors = _validate_intent(tmp_path, [_instrument_case([{"transaction_type": "HK_STOCK"}])])
    assert any("instruments[0].expression" in error for error in errors)


def test_instruments_only_allowed_for_swap(tmp_path: Path) -> None:
    case = _intent_case(expected={
        "product_type": "option_close",
        "intent": "close_order_query",
        "instruments": [{"expression": "600519.SH"}],
    })
    errors = _validate_intent(tmp_path, [case])
    assert any("instruments is only supported for product_type 'swap'" in error for error in errors)


# ── 意图集冻结上下文：quote_content / history / prev_product_type ──


def test_intent_case_may_still_replay_previous_reply(tmp_path: Path) -> None:
    """未冻结的多轮用例仍走主图 + mock 回放（与冻结用例并存）。"""
    case = _intent_case()
    for field_name in ("quote_content", "prev_product_type"):
        case["sub_scenes"][0].pop(field_name)
    case["sub_scenes"][0]["quote_previous"] = True
    assert _validate_intent(tmp_path, [case]) == []


def test_intent_case_rejects_mixing_frozen_context_and_replay(tmp_path: Path) -> None:
    """一条用例要么全部冻结、要么回放；混用时冻结的上下文会在回放模式下被静默忽略。"""
    case = _intent_case()
    case["sub_scenes"].append({
        "send_text": "确认撤单",
        "quote_previous": True,
        "expected": {"product_type": "option_close", "intent": "close_order_cancel_confirm"},
    })
    errors = _validate_intent(tmp_path, [case])
    assert any("mixes frozen context" in e for e in errors), errors


def test_intent_case_allows_quote_previous_false(tmp_path: Path) -> None:
    assert _validate_intent(tmp_path, [_intent_case(quote_previous=False)]) == []


def test_intent_case_accepts_frozen_history(tmp_path: Path) -> None:
    case = _intent_case()
    case["sub_scenes"][0]["history"] = [
        {"role": "user", "content": "我想平仓"},
        {"role": "assistant", "content": "以下是您的期权持仓："},
    ]
    assert _validate_intent(tmp_path, [case]) == []


def test_intent_case_rejects_malformed_frozen_context(tmp_path: Path) -> None:
    case = _intent_case(quote_content="")
    case["sub_scenes"][0]["history"] = [{"role": "bot", "content": "x"}, {"role": "user", "content": ""}, "x"]
    case["sub_scenes"][0]["prev_product_type"] = "unknown"
    errors = _validate_intent(tmp_path, [case])
    assert any("quote_content" in e and "non-empty" in e for e in errors), errors
    assert any("history[0]" in e and "role" in e for e in errors), errors
    assert any("history[1]" in e and "content" in e for e in errors), errors
    assert any("history[2]" in e for e in errors), errors
    assert any("prev_product_type" in e for e in errors), errors


def test_checker_runs_as_documented_script_without_pythonpath(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    _validate(tmp_path, [_valid_case()])
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, str(Path(checker.__file__).resolve()), "--root", str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fixture consistency: PASS" in result.stdout
