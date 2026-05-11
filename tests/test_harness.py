"""harness/ 单元测试 — golden / differ / runner / reporter / cli."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.cli import build_parser
from harness.differ import diff_fields, is_pass
from harness.golden import (
    GoldenCase,
    filter_by_category,
    index_by_category,
    load_golden,
)
from harness.reporter import render_failure_json, render_markdown, summarize
from harness.runner import run_case


# ============================================================
# golden loader
# ============================================================


def test_load_real_golden_jsonl() -> None:
    cases = load_golden("tests/fixtures/golden.jsonl")
    assert len(cases) > 0
    assert all(c.id and c.category and c.raw_content for c in cases)


def test_load_returns_empty_for_missing_path() -> None:
    assert load_golden("nonexistent.jsonl") == []


def test_index_and_filter_by_category() -> None:
    cases = [
        GoldenCase(id="a", category="swap/place_order", raw_content="x", expected={}),
        GoldenCase(id="b", category="swap/cancel", raw_content="y", expected={}),
        GoldenCase(id="c", category="option/quote", raw_content="z", expected={}),
    ]
    idx = index_by_category(cases)
    assert set(idx.keys()) == {"swap/place_order", "swap/cancel", "option/quote"}
    swap_only = filter_by_category(cases, "swap/")
    assert len(swap_only) == 2


# ============================================================
# differ
# ============================================================


def test_differ_passes_on_match() -> None:
    diffs = diff_fields({"intent": "x"}, {"intent": "x", "extra": "y"})
    assert is_pass(diffs)


def test_differ_reports_field_level_path() -> None:
    diffs = diff_fields(
        {"intent": "place_order_request"},
        {"intent": "confirm_order"},
    )
    assert len(diffs) == 1
    assert diffs[0].path == "intent"
    assert diffs[0].expected == "place_order_request"
    assert diffs[0].actual == "confirm_order"


def test_differ_recurses_into_nested_dict() -> None:
    diffs = diff_fields(
        {"params": {"price": 100, "quantity": 5}},
        {"params": {"price": 200, "quantity": 5}},
    )
    assert len(diffs) == 1
    assert diffs[0].path == "params.price"


def test_differ_handles_lists() -> None:
    diffs = diff_fields({"items": [1, 2, 3]}, {"items": [1, 2]})
    paths = [d.path for d in diffs]
    assert "items.length" in paths


# ============================================================
# runner — 真实跑一条 case
# ============================================================


@pytest.mark.asyncio
async def test_runner_executes_case() -> None:
    """harness 跑一条强信号 case（含"互换"关键词），验证规则层路由 → swap stub。

    ADR 0015 修订后，raw_content 必须含订单号或关键词才能不走 LLM 兜底；
    用"做一笔互换"让第 2 层关键词命中。
    """
    case = GoldenCase(
        id="harness-smoke",
        category="swap/place_order",
        raw_content="做一笔互换 100 手",
        expected={"product_type": "swap"},
    )
    result = await run_case(case)
    assert result.error is None
    assert result.final_state.get("product_type") == "swap"
    assert result.elapsed_ms >= 0


# ============================================================
# reporter
# ============================================================


def test_render_failure_json_includes_suspected_node() -> None:
    case = GoldenCase(
        id="g-fail",
        category="swap/place_order",
        raw_content="test",
        expected={"intent": "place_order_request"},
    )
    from harness.differ import FieldDiff
    from harness.runner import RunResult

    result = RunResult(
        case=case,
        final_state={"intent": "confirm_order", "trace": []},
        elapsed_ms=10,
    )
    diffs = [FieldDiff(path="intent", expected="place_order_request", actual="confirm_order")]
    rep = render_failure_json(result, diffs)

    assert rep["case_id"] == "g-fail"
    assert rep["diff"][0]["path"] == "intent"
    assert rep["suspected_node"] is not None  # 启发式给出
    assert rep["actual"] == {"intent": "confirm_order"}


def test_summarize_counts() -> None:
    from harness.differ import FieldDiff
    from harness.runner import RunResult

    pass_case = GoldenCase(id="p", category="swap/x", raw_content="", expected={})
    fail_case = GoldenCase(id="f", category="swap/x", raw_content="", expected={})
    pass_r = RunResult(case=pass_case, final_state={})
    fail_r = RunResult(case=fail_case, final_state={})
    fail_diff = [FieldDiff(path="x", expected=1, actual=2)]

    s = summarize([(pass_r, []), (fail_r, fail_diff)])
    assert s["total"] == 2
    assert s["passed"] == 1
    assert s["failed"] == 1


def test_render_markdown_smoke() -> None:
    from harness.runner import RunResult

    case = GoldenCase(id="g1", category="swap/x", raw_content="", expected={})
    md = render_markdown([(RunResult(case=case, final_state={}), [])])
    assert "PASS" in md
    assert "总数" in md


# ============================================================
# cli
# ============================================================


def test_cli_parser_accepts_run() -> None:
    parser = build_parser()
    ns = parser.parse_args(["run", "--all"])
    assert ns.cmd == "run"
    assert ns.all is True


def test_cli_parser_run_with_category() -> None:
    parser = build_parser()
    ns = parser.parse_args(["run", "--category", "swap/place_order"])
    assert ns.category == "swap/place_order"
