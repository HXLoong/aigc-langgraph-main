"""reporter 按 prompt 版本分桶测试（ADR 0003 灰度 A/B 对比）。

覆盖 `summarize_by_prompt_version`：
- 空 trace / 无 prompt_name 不参与统计
- 单版本统计正确
- 多版本分组 + PASS 率分别计算
- 同一 case 内 trace 重复（LangGraph 子图嵌入 reducer add）只算 1 次
- markdown 渲染包含版本对比表
"""
from __future__ import annotations

from typing import Any

from app.graph.state import TraceEntry
from harness.differ import FieldDiff
from harness.golden import GoldenCase
from harness.reporter import (
    render_markdown,
    summarize_by_prompt_version,
)
from harness.runner import RunResult


def _make_result(
    case_id: str,
    pass_case: bool,
    trace: list[TraceEntry] | list[dict[str, Any]] | None = None,
) -> tuple[RunResult, list[FieldDiff]]:
    """构造一条 RunResult（可指定 trace 内容 + 是否 PASS）。"""
    case = GoldenCase(
        id=case_id,
        category="test/dummy",
        raw_content="",
        expected={"intent": "place_order_request"},
    )
    final_state: dict[str, Any] = {
        "intent": (
            "place_order_request" if pass_case else "unknown_intent"
        ),
        "trace": trace or [],
    }
    result = RunResult(
        case=case, final_state=final_state, elapsed_ms=10, error=None
    )
    diffs = (
        []
        if pass_case
        else [
            FieldDiff(
                path="intent",
                expected="place_order_request",
                actual="unknown_intent",
            )
        ]
    )
    return result, diffs


# ============================================================
# 1. 空 / 无 prompt_name → 空结果
# ============================================================


def test_empty_results_returns_empty() -> None:
    assert summarize_by_prompt_version([]) == {}


def test_trace_without_llm_output_skipped() -> None:
    """trace 条目无 llm_output → 跳过统计。"""
    r1 = _make_result(
        "g1",
        pass_case=True,
        trace=[TraceEntry(node="swap_intent", decision="x")],
    )
    assert summarize_by_prompt_version([r1]) == {}


def test_trace_llm_output_without_prompt_name_skipped() -> None:
    """llm_output 存在但无 prompt_name → 跳过。"""
    r1 = _make_result(
        "g1",
        pass_case=True,
        trace=[
            TraceEntry(
                node="swap_intent",
                llm_output={"type": "place_order_request"},
            )
        ],
    )
    assert summarize_by_prompt_version([r1]) == {}


# ============================================================
# 2. 单版本统计
# ============================================================


def test_single_version_pass_rate_correct() -> None:
    results = []
    # 5 PASS + 1 FAIL，全走 v1
    for i in range(5):
        results.append(
            _make_result(
                f"g{i}",
                pass_case=True,
                trace=[
                    TraceEntry(
                        node="swap_intent",
                        llm_output={"prompt_name": "intent"},
                    )
                ],
            )
        )
    results.append(
        _make_result(
            "g_fail",
            pass_case=False,
            trace=[
                TraceEntry(
                    node="swap_intent",
                    llm_output={"prompt_name": "intent"},
                )
            ],
        )
    )

    out = summarize_by_prompt_version(results)
    assert out["swap_intent"]["intent"]["total"] == 6
    assert out["swap_intent"]["intent"]["passed"] == 5
    assert out["swap_intent"]["intent"]["failed"] == 1
    assert abs(out["swap_intent"]["intent"]["pass_rate"] - 5 / 6) < 1e-6


# ============================================================
# 3. 多版本（v1 + v2）分组
# ============================================================


def test_multi_version_split_correctly() -> None:
    """v1 全 PASS，v2 部分 FAIL：分组统计独立。"""
    results = []
    # v1: 8/8 PASS
    for i in range(8):
        results.append(
            _make_result(
                f"v1-{i}",
                pass_case=True,
                trace=[
                    TraceEntry(
                        node="swap_intent",
                        llm_output={"prompt_name": "intent"},
                    )
                ],
            )
        )
    # v2: 1 PASS + 1 FAIL
    results.append(
        _make_result(
            "v2-pass",
            pass_case=True,
            trace=[
                TraceEntry(
                    node="swap_intent",
                    llm_output={"prompt_name": "intent_v2"},
                )
            ],
        )
    )
    results.append(
        _make_result(
            "v2-fail",
            pass_case=False,
            trace=[
                TraceEntry(
                    node="swap_intent",
                    llm_output={"prompt_name": "intent_v2"},
                )
            ],
        )
    )

    out = summarize_by_prompt_version(results)
    assert out["swap_intent"]["intent"]["total"] == 8
    assert out["swap_intent"]["intent"]["passed"] == 8
    assert out["swap_intent"]["intent"]["pass_rate"] == 1.0

    assert out["swap_intent"]["intent_v2"]["total"] == 2
    assert out["swap_intent"]["intent_v2"]["passed"] == 1
    assert out["swap_intent"]["intent_v2"]["pass_rate"] == 0.5


# ============================================================
# 4. trace 重复 → 同一 case 内只算 1 次
# ============================================================


def test_duplicate_trace_within_case_counted_once() -> None:
    """LangGraph 子图嵌入会让 trace reducer add 重复，只算 1 次。"""
    duplicated_trace = [
        TraceEntry(
            node="swap_intent", llm_output={"prompt_name": "intent_v2"}
        ),
        TraceEntry(
            node="swap_intent", llm_output={"prompt_name": "intent_v2"}
        ),
        TraceEntry(
            node="swap_intent", llm_output={"prompt_name": "intent_v2"}
        ),
    ]
    r = _make_result("g_dup", pass_case=True, trace=duplicated_trace)
    out = summarize_by_prompt_version([r])
    assert out["swap_intent"]["intent_v2"]["total"] == 1
    assert out["swap_intent"]["intent_v2"]["passed"] == 1


# ============================================================
# 5. 跨节点（多个不同节点都用了 prompt_name）
# ============================================================


def test_multiple_nodes_tracked_separately() -> None:
    """swap_intent + option_intent 都记 prompt_name → 各自独立桶。"""
    trace = [
        TraceEntry(node="swap_intent", llm_output={"prompt_name": "intent"}),
        TraceEntry(
            node="option_intent", llm_output={"prompt_name": "intent_v3"}
        ),
    ]
    r = _make_result("g_multi", pass_case=True, trace=trace)
    out = summarize_by_prompt_version([r])
    assert "swap_intent" in out
    assert "option_intent" in out
    assert "intent" in out["swap_intent"]
    assert "intent_v3" in out["option_intent"]


# ============================================================
# 6. dict 形式的 trace 也能识别（兼容）
# ============================================================


def test_dict_trace_entries_recognized() -> None:
    """trace 元素是 dict（langgraph 序列化后场景）也能识别。"""
    trace = [
        {
            "node": "swap_intent",
            "llm_output": {"prompt_name": "intent_v2"},
        }
    ]
    r = _make_result("g_dict", pass_case=True, trace=trace)
    out = summarize_by_prompt_version([r])
    assert out["swap_intent"]["intent_v2"]["total"] == 1


# ============================================================
# 7. markdown 渲染含版本对比表（仅 ≥ 2 个版本时）
# ============================================================


def test_render_markdown_includes_version_comparison_when_canary_active() -> (
    None
):
    """v1 + v2 同时出现 → markdown 输出对比表。"""
    results = [
        _make_result(
            "g_v1",
            pass_case=True,
            trace=[
                TraceEntry(
                    node="swap_intent",
                    llm_output={"prompt_name": "intent"},
                )
            ],
        ),
        _make_result(
            "g_v2",
            pass_case=True,
            trace=[
                TraceEntry(
                    node="swap_intent",
                    llm_output={"prompt_name": "intent_v2"},
                )
            ],
        ),
    ]

    md = render_markdown(results)
    assert "ADR 0003" in md
    assert "swap_intent" in md
    assert "`intent`" in md
    assert "`intent_v2`" in md


def test_render_markdown_skips_section_when_only_one_version() -> None:
    """只有 v1 时不渲染 A/B 对比表（无对比价值）。"""
    results = [
        _make_result(
            "g1",
            pass_case=True,
            trace=[
                TraceEntry(
                    node="swap_intent",
                    llm_output={"prompt_name": "intent"},
                )
            ],
        ),
    ]
    md = render_markdown(results)
    # swap_intent 在汇总章节出现是 OK 的（fail_by_category 等不会含），
    # 关键是不应出现版本对比表标题
    assert "ADR 0003 灰度 A/B 对比" not in md


def test_render_markdown_skips_section_when_no_prompt_versioning() -> None:
    """根本没节点记 prompt_name → 不渲染对比表。"""
    results = [_make_result("g1", pass_case=True, trace=[])]
    md = render_markdown(results)
    assert "ADR 0003" not in md
