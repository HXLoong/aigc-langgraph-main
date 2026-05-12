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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from harness.differ import FieldDiff, is_pass
from harness.runner import RunResult
from harness.token_tracker import TokenUsage, aggregate as aggregate_token_usage


#: case source → PASS 阈值（grill-with-docs 2026-05-10 第 4 决策）
SOURCE_PASS_THRESHOLDS: dict[str, float] = {
    "business_seed": 0.90,
    "llm_paraphrase": 0.80,
    "production_log": 0.85,
}


# ============================================================
# 启发式定位（M2 升级版 · ADR 0001 D7）
# ============================================================


#: 字段根名 + product_type → 节点名（M2 真实节点映射）
#: 同字段被多个子图节点写时（如 intent / place_params），按 product_type 分流
_FIELD_BY_PRODUCT: dict[str, dict[str, str]] = {
    "intent": {
        "swap": "swap_intent",
        "option": "option_intent",
        "option_close": "close_intent",
    },
    "place_params": {
        "swap": "swap_place_order",
        "option": "option_extract_place_or_modify",
        "option_close": "close_place_close",
    },
    "tickers": {
        # tickers 由含 ticker resolver 集成的节点写
        "swap": "swap_place_order",
        "option": "option_extract_inquiry",
    },
    "close_params": {
        # close 子图多个节点都写 close_params；按 intent 进一步细分
        "option_close": "close_holding_query",  # 默认；具体节点见 trace
    },
    "confirm": {
        "option_close": "close_confirm_close",
        # swap.confirm 合并版后续 PR 实施
    },
    "cancel_params": {
        "option_close": "close_cancel_close",
    },
}


#: 字段根名兜底（product_type 未知或不在分流表）
_FIELD_FALLBACK: dict[str, str] = {
    "product_type": "intent_route",
    "intent": "intent_route",  # 当 product_type=unknown 时漏判在 intent_route
    "tickers": "ticker_react_agent",
}


#: 节点名 → 提示词文件路径
_NODE_TO_PROMPT: dict[str, str] = {
    "intent_route": "app/prompts/router/product_type.md",
    "ticker_react_agent": "app/prompts/ticker/infer_code.md",
    "swap_intent": "app/prompts/swap/intent.md",
    "swap_place_order": "app/prompts/swap/place_order.md",
    "option_intent": "app/prompts/option/intent.md",
    "option_extract_inquiry": "app/prompts/option/extract_inquiry.md",
    "option_extract_place_or_modify": (
        "app/prompts/option/extract_place_or_modify.md"
    ),
    "close_intent": "app/prompts/option_close/intent.md",
    "close_holding_query": "app/prompts/option_close/holding_query.md",
    "close_place_close": "app/prompts/option_close/place_close.md",
    "close_confirm_close": "app/prompts/option_close/confirm_close.md",
    "close_cancel_close": "app/prompts/option_close/cancel_close.md",
}


def _suspect(
    diffs: list[FieldDiff], final_state: dict[str, Any] | None = None
) -> tuple[str | None, str | None]:
    """从 diffs + final_state 推断嫌疑节点 + 提示词文件路径。

    优先级：
    1. 字段根名 + product_type 命中 _FIELD_BY_PRODUCT → 精确节点
    2. 否则查 _FIELD_FALLBACK → 兜底节点
    3. 都不命中 → (None, None)

    M2 升级（ADR 0001 D7）：替代 M1 占位的扁平 _FIELD_TO_NODE_HINTS。
    后续可进一步通过 trace 反向追踪写入字段的最后一个节点。
    """
    if not diffs:
        return None, None

    root = diffs[0].path.split(".")[0].split("[")[0]
    product_type = (
        final_state.get("product_type") if final_state is not None else None
    )

    # 第 1 层：按 product_type 分流
    by_product = _FIELD_BY_PRODUCT.get(root, {})
    if product_type and product_type in by_product:
        node = by_product[product_type]
        return node, _NODE_TO_PROMPT.get(node)

    # 第 2 层：兜底
    node = _FIELD_FALLBACK.get(root)
    if node:
        return node, _NODE_TO_PROMPT.get(node)

    return None, None


# ============================================================
# 单 case 失败报告
# ============================================================


def render_failure_json(
    result: RunResult, diffs: list[FieldDiff]
) -> dict[str, Any]:
    """构造单 case 的失败 JSON 报告。"""
    suspected_node, suspected_prompt = _suspect(diffs, result.final_state)

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

    # F4.1 灰度成本观测：聚合 token 使用
    token_total = aggregate_token_usage(
        [r.token_usage for r, _ in results if r.token_usage]
    )

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / total) if total else 0.0,
        "by_category": dict(by_category),
        "fail_by_category": dict(fail_by_category),
        "token_usage": token_total.model_dump(),
    }


def summarize_by_source(
    results: list[tuple[RunResult, list[FieldDiff]]],
) -> dict[str, dict[str, Any]]:
    """按 case source 分桶统计 PASS 率 + 阈值检查。

    grill-with-docs 2026-05-10 第 4 决策：
    - business_seed PASS ≥ 90%
    - llm_paraphrase PASS ≥ 80%
    - production_log PASS ≥ 85%
    """
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "passed": 0}
    )
    for r, d in results:
        src = getattr(r.case, "source", "business_seed")
        counts[src]["total"] += 1
        if is_pass(d):
            counts[src]["passed"] += 1

    summary: dict[str, dict[str, Any]] = {}
    for src, c in counts.items():
        total = c["total"]
        passed = c["passed"]
        rate = (passed / total) if total else 0.0
        threshold = SOURCE_PASS_THRESHOLDS.get(src, 0.0)
        summary[src] = {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": rate,
            "threshold": threshold,
            "meets_threshold": rate >= threshold,
        }
    return summary


def summarize_by_prompt_version(
    results: list[tuple[RunResult, list[FieldDiff]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """按 trace 中 `llm_output.prompt_name` 分组统计 PASS 率（节点 → 版本）。

    用途：ADR 0003 灰度上线后，按节点的不同 prompt 版本对比 PASS 率，
    支撑实证 A/B 决策（v2 是否扩流量、是否回滚）。

    数据来源：节点函数在 trace 中写 `llm_output={"prompt_name": <name>, ...}`。
    无 prompt_name 的 trace 条目跳过（不影响主统计）。

    返回结构：
        {
          "swap_intent": {
            "intent":    {"total": 28, "passed": 27, "failed": 1, "pass_rate": 0.964},
            "intent_v2": {"total":  2, "passed":  2, "failed": 0, "pass_rate": 1.000},
          },
          ...
        }

    去重原则：每条 case 对同一 (node, prompt_name) 只计 1 次（LangGraph 子图嵌入
    reducer add 会让 trace 重复，但 PASS 率口径上重复无意义）。
    """
    bucket: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"total": 0, "passed": 0})
    )

    for r, d in results:
        passed = is_pass(d)
        seen: set[tuple[str, str]] = set()
        for entry in r.final_state.get("trace", []):
            # entry 可能是 TraceEntry 实例或 dict（兼容两种表达）
            llm_output = (
                getattr(entry, "llm_output", None)
                if not isinstance(entry, dict)
                else entry.get("llm_output")
            )
            node_name = (
                getattr(entry, "node", None)
                if not isinstance(entry, dict)
                else entry.get("node")
            )
            if not isinstance(llm_output, dict) or not node_name:
                continue
            prompt_name = llm_output.get("prompt_name")
            if not prompt_name:
                continue

            key = (node_name, prompt_name)
            if key in seen:
                continue
            seen.add(key)

            bucket[node_name][prompt_name]["total"] += 1
            if passed:
                bucket[node_name][prompt_name]["passed"] += 1

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for node, versions in bucket.items():
        out[node] = {}
        for ver, stats in versions.items():
            t = stats["total"]
            p = stats["passed"]
            out[node][ver] = {
                "total": t,
                "passed": p,
                "failed": t - p,
                "pass_rate": (p / t) if t else 0.0,
            }
    return out


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

    # F4.1 灰度成本观测：token 使用段（即使为 0 也输出，方便确认 tracker 工作）
    tu = s.get("token_usage") or {}
    if tu.get("call_count") or tu.get("total_tokens"):
        lines.append("## LLM token 使用（F4.1 灰度成本观测）")
        lines.append("")
        lines.append(
            f"- LLM 调用次数: {tu.get('call_count', 0)}"
        )
        lines.append(
            f"- prompt tokens: {tu.get('prompt_tokens', 0):,}"
        )
        lines.append(
            f"- completion tokens: {tu.get('completion_tokens', 0):,}"
        )
        lines.append(
            f"- 合计: {tu.get('total_tokens', 0):,}"
        )
        by_model = tu.get("by_model") or {}
        if by_model:
            lines.append("")
            lines.append("| 模型 | prompt | completion | 合计 |")
            lines.append("|---|---|---|---|")
            for model in sorted(by_model):
                counts = by_model[model]
                pt = counts.get("prompt", 0)
                ct = counts.get("completion", 0)
                lines.append(
                    f"| `{model}` | {pt:,} | {ct:,} | {pt + ct:,} |"
                )
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

    # ADR 0001 D9.2 + grill-with-docs 第 4 决策：按 case source 分桶
    by_source = summarize_by_source(results)
    if by_source:
        lines.append("## 按 case 来源分桶（B+C 阈值检查）")
        lines.append("")
        lines.append("| 来源 | 总数 | PASS | 通过率 | 阈值 | 是否达标 |")
        lines.append("|---|---|---|---|---|---|")
        for src, info in sorted(by_source.items()):
            ok = "✅" if info["meets_threshold"] else "❌"
            lines.append(
                f"| `{src}` | {info['total']} | {info['passed']} | "
                f"{info['pass_rate']:.1%} | {info['threshold']:.0%} | {ok} |"
            )
        lines.append("")

    # ADR 0003 灰度：按 prompt 版本分桶（A/B 对比）
    by_prompt = summarize_by_prompt_version(results)
    multi_version_nodes = sorted(
        node for node, versions in by_prompt.items() if len(versions) >= 2
    )
    if multi_version_nodes:
        lines.append("## 按 prompt 版本分桶（ADR 0003 灰度 A/B 对比）")
        lines.append("")
        for node in multi_version_nodes:
            versions = by_prompt[node]
            lines.append(f"### `{node}`")
            lines.append("")
            lines.append("| 版本 | 总数 | PASS | FAIL | 通过率 |")
            lines.append("|---|---|---|---|---|")
            # 总数倒序，便于看主版本 vs 灰度
            for ver, info in sorted(
                versions.items(), key=lambda kv: -kv[1]["total"]
            ):
                lines.append(
                    f"| `{ver}` | {info['total']} | {info['passed']} | "
                    f"{info['failed']} | {info['pass_rate']:.1%} |"
                )
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
