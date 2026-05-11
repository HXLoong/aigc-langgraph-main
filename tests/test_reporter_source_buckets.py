"""reporter 按 source 分桶统计测试（grill-with-docs 第 4 决策）。"""
from __future__ import annotations

from harness.differ import FieldDiff
from harness.golden import GoldenCase
from harness.reporter import (
    SOURCE_PASS_THRESHOLDS,
    render_markdown,
    summarize_by_source,
)
from harness.runner import RunResult


def _make_result(
    case_id: str, source: str, pass_case: bool
) -> tuple[RunResult, list[FieldDiff]]:
    case = GoldenCase(
        id=case_id,
        category="test/dummy",
        raw_content="",
        expected={"product_type": "swap"},
        source=source,  # type: ignore[arg-type]
    )
    result = RunResult(
        case=case,
        final_state={"product_type": "swap"} if pass_case else {"product_type": "option"},
        elapsed_ms=10,
        error=None,
    )
    diffs = (
        []
        if pass_case
        else [FieldDiff(path="product_type", expected="swap", actual="option")]
    )
    return result, diffs


def test_thresholds_match_grill_decision() -> None:
    """grill-with-docs 第 4 决策的阈值必须对得上。"""
    assert SOURCE_PASS_THRESHOLDS["business_seed"] == 0.90
    assert SOURCE_PASS_THRESHOLDS["llm_paraphrase"] == 0.80
    assert SOURCE_PASS_THRESHOLDS["production_log"] == 0.85


def test_summarize_by_source_b_bucket_meets_threshold() -> None:
    # 业务方种子：10 条 9 PASS = 90%，正好达阈
    results = [
        _make_result(f"b{i}", "business_seed", pass_case=(i < 9))
        for i in range(10)
    ]
    summary = summarize_by_source(results)
    assert "business_seed" in summary
    assert summary["business_seed"]["total"] == 10
    assert summary["business_seed"]["passed"] == 9
    assert summary["business_seed"]["pass_rate"] == 0.9
    assert summary["business_seed"]["meets_threshold"] is True


def test_summarize_by_source_b_bucket_below_threshold() -> None:
    # 8 PASS / 10 = 80%，低于 B 桶 90% 阈值
    results = [
        _make_result(f"b{i}", "business_seed", pass_case=(i < 8))
        for i in range(10)
    ]
    summary = summarize_by_source(results)
    assert summary["business_seed"]["meets_threshold"] is False


def test_summarize_by_source_c_bucket_threshold() -> None:
    # LLM 生成：8 PASS / 10 = 80% 正好达阈
    results = [
        _make_result(f"c{i}", "llm_paraphrase", pass_case=(i < 8))
        for i in range(10)
    ]
    summary = summarize_by_source(results)
    assert summary["llm_paraphrase"]["meets_threshold"] is True
    assert summary["llm_paraphrase"]["pass_rate"] == 0.8


def test_summarize_by_source_mixed() -> None:
    """B 和 C 混合时分别统计，互不影响。"""
    results = [
        # B 桶 5/5 = 100%（达阈 90%）
        _make_result("b1", "business_seed", True),
        _make_result("b2", "business_seed", True),
        _make_result("b3", "business_seed", True),
        _make_result("b4", "business_seed", True),
        _make_result("b5", "business_seed", True),
        # C 桶 4/5 = 80%（达阈 80%）
        _make_result("c1", "llm_paraphrase", True),
        _make_result("c2", "llm_paraphrase", True),
        _make_result("c3", "llm_paraphrase", True),
        _make_result("c4", "llm_paraphrase", True),
        _make_result("c5", "llm_paraphrase", False),
    ]
    summary = summarize_by_source(results)
    assert summary["business_seed"]["meets_threshold"] is True
    assert summary["llm_paraphrase"]["meets_threshold"] is True


def test_render_markdown_includes_source_bucket_section() -> None:
    """markdown 报告必须含按 source 分桶段。"""
    results = [
        _make_result("b1", "business_seed", True),
        _make_result("c1", "llm_paraphrase", False),
    ]
    md = render_markdown(results)
    assert "按 case 来源分桶" in md
    assert "business_seed" in md
    assert "llm_paraphrase" in md
