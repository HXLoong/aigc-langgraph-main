"""Reporter — 输出 JSON 失败报告 + markdown 汇总（ADR 0001 D7 修订版）。

JSON 失败报告（机器读 / AI 工具消费）：
{
  "case_id": "g042",
  "raw_content": "...",
  "expected": {...},
  "actual": {...},
  "diff": [{"path": "params.price_type", "expected": "limit", "actual": "market"}],
  "trace": [{"node": "...", "decision": "...", "elapsed_ms": ...}],
  "suspected_node": "swap.place_order",
  "suspected_prompt": "app/prompts/swap/place_order.md"
}

Markdown 汇总（人读）：含 PASS/FAIL 计数、Top 5 失败 case、各 category 通过率。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from harness.differ import FieldDiff, is_pass
from harness.runner import RunResult


# ============================================================
# 启发式定位（M1 简版）
# ============================================================


# diff path 关键词 → 嫌疑节点名 的简单映射
# M2 阶段接入真实节点后扩展为"节点 → 写入字段集"的精确反查
_FIELD_TO_NODE_HINTS = {
    "intent": "intent_route",  # M1 占位；M2 由 swap.intent / option.intent_extract 等
    "product_type": "intent_route",
    "place_params": "swap.place_order",
    "cancel_params": "swap.cancel",
    "confirm": "swap.confirm",
    "query_filter": "swap.query_order",
    "close_params": "close.place_close",
    "tickers": "ticker.react_agent",
}


def _suspect(diffs: list[FieldDiff]) -> tuple[str | None, str | None]:
    """从 diffs 推断嫌疑节点 + prompt 文件路径。

    M1 简版：取第一个 diff path 的根字段，查 _FIELD_TO_NODE_HINTS。
    M2 阶段：扩展为根据 trace 反向追踪写入字段的最后一个节点。
    """
    if not diffs:
        return None, None

    root = diffs[0].path.split(".")[0].split("[")[0]
    node = _FIELD_TO_NODE_HINTS.get(root)
    if node is None:
        return None, None

    # 推断 prompt 文件路径（约定：app/prompts/<category>/<name>.md）
    if "." in node:
        category, name = node.split(".", 1)
        prompt = f"app/prompts/{category}/{name}.md"
    else:
        prompt = None

    return node, prompt


# ============================================================
# 单 case 失败报告
# ============================================================


def render_failure_json(
    result: RunResult, diffs: list[FieldDiff]
) -> dict[str, Any]:
    """构造单 case 的失败 JSON 报告。"""
    suspected_node, suspected_prompt = _suspect(diffs)

    return {
        "case_id": result.case.id,
        "category": result.case.category,
        "raw_content": result.case.raw_content,
        "expected": result.case.expected,
        "actual": _extract_actual(result.final_state, result.case.expected),
        "diff": [d.model_dump() for d in diffs],
        "trace": result.final_state.get("trace", []),
        "elapsed_ms": result.elapsed_ms,
        "error": result.error,
        "suspected_node": suspected_node,
        "suspected_prompt": suspected_prompt,
    }


def _extract_actual(
    final_state: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    """从 final_state 抽出 expected 关心的字段（避免 trace / error 等噪音污染报告）。"""
    out: dict[str, Any] = {}
    for k in expected.keys():
        if k in final_state:
            out[k] = final_state[k]
    return out


def write_failure_json(
    result: RunResult, diffs: list[FieldDiff], out_dir: str | Path
) -> Path:
    """写一份单 case 的 JSON 报告到磁盘。"""
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    fp = p / f"{result.case.id}.json"
    fp.write_text(
        json.dumps(
            render_failure_json(result, diffs), ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    return fp


# ============================================================
# 汇总报告
# ============================================================


def summarize(
    results: list[tuple[RunResult, list[FieldDiff]]],
) -> dict[str, Any]:
    """生成 JSON 汇总。"""
    total = len(results)
    passed = sum(1 for _, d in results if is_pass(d))
    failed = total - passed

    by_category: Counter[str] = Counter()
    fail_by_category: Counter[str] = Counter()
    for r, d in results:
        by_category[r.case.category] += 1
        if not is_pass(d):
            fail_by_category[r.case.category] += 1

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / total) if total else 0.0,
        "by_category": dict(by_category),
        "fail_by_category": dict(fail_by_category),
    }


def render_markdown(
    results: list[tuple[RunResult, list[FieldDiff]]],
) -> str:
    """生成 markdown 汇总报告（人读）。"""
    s = summarize(results)
    lines: list[str] = []
    lines.append("# Harness 报告")
    lines.append("")
    lines.append(f"- 总数: {s['total']}")
    lines.append(f"- PASS: {s['passed']}")
    lines.append(f"- FAIL: {s['failed']}")
    lines.append(f"- 通过率: {s['pass_rate']:.1%}")
    lines.append("")

    if s["fail_by_category"]:
        lines.append("## 各 category 失败数（Top 5）")
        lines.append("")
        for cat, cnt in sorted(
            s["fail_by_category"].items(), key=lambda kv: -kv[1]
        )[:5]:
            total = s["by_category"].get(cat, 0)
            lines.append(f"- `{cat}`: {cnt} / {total}")
        lines.append("")

    failures = [(r, d) for r, d in results if not is_pass(d)]
    if failures:
        lines.append("## 失败 case 列表")
        lines.append("")
        for r, d in failures[:20]:
            paths = ", ".join(diff.path for diff in d) or "(error)"
            lines.append(f"- `{r.case.id}` ({r.case.category}): {paths}")
        if len(failures) > 20:
            lines.append(f"- ... 共 {len(failures)} 条失败")
        lines.append("")

    return "\n".join(lines)
