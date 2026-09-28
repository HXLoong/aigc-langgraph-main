"""统一 HTTP 执行及确定性评分，CLI 和 Langfuse Experiment 共用。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import httpx

from harness.evaluation import report_case, turn_diffs
from harness.evaluators import instrument_match, intent_match, rejection_match
from harness.golden import GoldenCase, dataset_expected
from harness.intent_context import requires_replay
from harness.intent_runner import run_frozen_case
from harness.multi_turn import run_case_multi


def intent_evaluations(case: GoldenCase, output: dict[str, Any]) -> list[dict[str, Any]]:
    """复用平台同源代码评分；没有标签时不能产生默认通过分数。"""
    context = SimpleNamespace(experiment=SimpleNamespace(item_expected_output=dataset_expected(case)),
                              observation=SimpleNamespace(output=output))
    evaluators: list[Callable[[Any], Any]] = [intent_match.evaluate]
    if any(turn.expected.get("instruments") for turn in case.turns):
        evaluators.append(instrument_match.evaluate)
    if any(turn.expected.get("rejection") for turn in case.turns):
        evaluators.append(rejection_match.evaluate)
    return [{"name": score.name, "value": float(bool(score.value)), "comment": score.comment,
             "metadata": score.metadata}
            for evaluator in evaluators for score in evaluator(context).scores]


async def run_case(
    case: GoldenCase, *, suite: str, base_url: str, user_id: str, room_id: str,
    client: httpx.AsyncClient | None = None,
    before_turn: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    timeout: float = 90, turn_interval: float = 1,
    trace_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行入口与评分入口只各有一份，结果包含字段差异和关联 ID。"""
    # 1. 冻结意图只执行解析节点；业务、多轮回放和可见拒绝走主图 HTTP。
    frozen = suite == "intent" and not requires_replay([turn.model_dump() for turn in case.turns])
    frozen = frozen and not any(turn.expected.get("rejection") for turn in case.turns)
    if frozen:
        result = await run_frozen_case(case, base_url=base_url, user_id=user_id, client=client,
                                       timeout=timeout, trace_metadata=trace_metadata)
    else:
        result = await run_case_multi(case, base_url=base_url, user_id=user_id, room_id=room_id,
            client=client, before_turn=before_turn, timeout=timeout, turn_interval=turn_interval,
            trace_metadata=trace_metadata)

    # 2. 业务比较所有明确字段；意图集按各自的稳定语义投影比较。
    report = report_case(case, result, turn_diffs(case, result) if suite == "business" else {})
    report["mode"] = "intent_node" if frozen else "main_graph_http"
    if suite == "intent":
        evaluations = intent_evaluations(case, report)
        if result.failure and not any(turn.expected.get("rejection") for turn in case.turns):
            evaluations.append({"name": "det_execution_pass", "value": 0.0, "comment": "解析执行失败"})
        report["passed"] = bool(evaluations) and all(item["value"] == 1 for item in evaluations)
        report["status"] = "PASS" if report["passed"] else "FAIL"
    else:
        evaluations = [{"name": "det_business_pass", "value": float(report["passed"]),
                        "comment": "全部明确断言通过" if report["passed"] else str(report["failure"] or "存在字段或文本差异")}]
    report["evaluations"] = evaluations
    report["expected_rejection"] = any(turn.expected.get("rejection") for turn in case.turns)
    report["reply_text"] = "\n".join(turn.reply_text for turn in result.turns)
    return report
