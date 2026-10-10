"""本地与平台共用的确定性差异和报告；评分不调用模型。"""
from __future__ import annotations

from typing import Any

from harness.differ import (
    FieldDiff,
    check_case_assertions,
    check_structured_assertions,
    check_text_assertions,
)
from harness.golden import GoldenCase, TurnSpec, dataset_expected, dataset_input
from harness.multi_turn import MultiTurnResult


def parameter_coverage(case: GoldenCase) -> dict[str, Any]:
    """写入参数标注缺口单列待验收，不改变用户已确认的现有断言评分。"""
    if case.category.startswith("intent/"):
        return {"status": "not_applicable", "missing_turns": [], "meaning": "意图集不承担业务参数验收"}
    reads = {"query_order_status", "close_order_query", "close_order_order_query", "unknown_intent"}
    parameter_fields = {"place_params", "cancel_params", "confirm", "close_params"}
    missing = []
    for index, turn in enumerate(case.turns, 1):
        intent = turn.expected.get("intent")
        request = turn.expected.get("backend_request") or {}
        request_parameters = isinstance(request, dict) and any(
            request.get(key) for key in ("orderList", "closeOrderReqVO", "optionRfq")
        )
        if intent and intent not in reads and not request_parameters and not any(turn.expected.get(key) for key in parameter_fields):
            missing.append(index)
    return {"status": "pending_business_acceptance" if missing else "present",
            "missing_turns": missing, "meaning": "结构化参数断言存在性，不代表完整字段覆盖"}


def turn_diffs(
    case: GoldenCase, result: MultiTurnResult, backend: str = "real"
) -> dict[int | str, list[FieldDiff]]:
    """逐轮比较明确断言；缺少期望或实际轮次都记录失败原因。"""
    diffs: dict[int | str, list[FieldDiff]] = {}
    for outcome, spec in zip(result.turns, case.turns, strict=False):
        turn_diffs = check_text_assertions(
            outcome.reply_text, spec, allow_dry_run=backend == "dry-run"
        )
        turn_diffs.extend(check_structured_assertions(
            outcome.outputs, spec.expected, quote_content=outcome.quote_content,
        ))
        if not (spec.expected or spec.response_contains or spec.response_contains_any
                or spec.response_not_contains or (case.expected_scope == "any_turn" and case.expected)):
            turn_diffs.append(FieldDiff(path="expected", expected="explicit assertions", actual="missing"))
        diffs[outcome.index] = turn_diffs
    if case.expected_scope == "any_turn":
        case_diffs = check_case_assertions(
            [outcome.outputs for outcome in result.turns], case.expected,
            quote_contents=[outcome.quote_content for outcome in result.turns],
        )
        if case_diffs:
            diffs["case"] = case_diffs
    if len(result.turns) < len(case.turns):
        # 执行器未附失败元数据也不能掩盖缺失的轮次。
        failure = result.failure or {}
        stop_turn, kind = failure.get("turn"), failure.get("kind", "missing_turn")
        for index in range(len(result.turns) + 1, len(case.turns) + 1):
            diffs[index] = [
                FieldDiff(
                    path="runtime",
                    expected="turn executed",
                    actual=f"not executed: early stop at turn {stop_turn} ({kind})",
                )
            ]
    if not case.turns:
        diffs["case"] = [FieldDiff(path="expected", expected="nonempty case", actual="no turns")]
    return diffs


def case_status(result: MultiTurnResult, diffs: dict[int | str, list[FieldDiff]]) -> str:
    """PASS / FAIL / REJECTED：业务拒绝不算 PASS，单独成桶（ADR 0024 D6）。"""
    if any(diffs.values()):
        return "FAIL"
    if result.failure is None:
        return "PASS"
    return "REJECTED" if result.failure.get("kind") == "business_reject" else "FAIL"


def turn_assertions(spec: TurnSpec) -> dict[str, Any]:
    """保存本轮原始标注，不把关键词约束拼成不存在的完整预期回复。"""
    return spec.model_dump(include={
        "expected", "response_contains", "response_contains_any", "response_not_contains",
    })


def report_case(
    case: GoldenCase, result: MultiTurnResult, diffs: dict[int | str, list[FieldDiff]]
) -> dict[str, Any]:
    """生成可复核报告，实际状态和期望都保留以支持平台一致性评分。"""
    status = case_status(result, diffs)
    return {
        "case_id": case.id,
        "name": case.name,
        "category": case.category,
        "dialect": case.dialect,
        # 输入、期望和实际结果一起冻结，未来数据更新也能复核旧批次。
        "input": dataset_input(case) if case.turns else {},
        "expected_output": dataset_expected(case) if case.turns else {},
        "expected_scope": case.expected_scope,
        "execution_before": case.execution_before,
        "case_expected": case.expected,
        "case_diff": [item.model_dump() for item in diffs.get("case", [])],
        "source_path": case.source_path,
        "source_line": case.source_line,
        "conversation_id": result.conversation_id,
        "langfuse_trace_id": result.langfuse_trace_id,
        "observation_id": result.observation_id,
        "trace_status": result.trace_status,
        "parameter_assertion_coverage": parameter_coverage(case),
        "status": status,
        "passed": status == "PASS",
        "failure": result.failure,
        "turns": [
            {
                "turn": outcome.index,
                "scene": outcome.scene,
                "raw": outcome.send_text,
                "source_text": case.turns[outcome.index - 1].send_text,
                "at_bot": outcome.at_bot,
                "fast_query": case.turns[outcome.index - 1].fast_query,
                "robot_version": case.turns[outcome.index - 1].robot_version,
                "existing_command": case.turns[outcome.index - 1].existing_command,
                "entry_branch": outcome.outputs.get("entry_branch"),
                "reply": outcome.reply_text,
                "quote_passed": outcome.quote_passed,
                "quote_content": outcome.quote_content,
                "history": case.turns[outcome.index - 1].history,
                "prev_product_type": case.turns[outcome.index - 1].prev_product_type,
                "assertions": turn_assertions(case.turns[outcome.index - 1]),
                "product_type": outcome.product_type,
                "intent": outcome.intent,
                "tickers": outcome.tickers,
                "place_params": outcome.place_params,
                "outputs": outcome.outputs,
                "api_code": outcome.api_code,
                "api_result": outcome.api_result,
                "error": outcome.error,
                "trace": outcome.trace,
                "trace_id": outcome.outputs.get("trace_id"),
                "langfuse_trace_id": outcome.outputs.get("langfuse_trace_id"),
                "observation_id": outcome.outputs.get("observation_id"),
                "trace_url": outcome.outputs.get("trace_url"),
                "elapsed_ms": outcome.elapsed_ms,
                "diff": [item.model_dump() for item in diffs.get(outcome.index, [])],
            }
            for outcome in result.turns
        ],
        # 未执行轮独立列出，不给旧评分器增加伪造的实际结果。
        "unexecuted_turns": [
            {"turn": index, "scene": spec.scene, "raw": spec.send_text,
             "assertions": turn_assertions(spec), "reason": result.failure or "missing_turn",
             "diff": [item.model_dump() for item in diffs.get(index, [])]}
            for index, spec in enumerate(case.turns, 1)
            if index not in {outcome.index for outcome in result.turns}
        ],
    }


def summarize(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """按同一分母统计 PASS、FAIL、REJECTED，业务拒绝不并入通过。"""
    counts = {
        status: sum(1 for r in reports if r["status"] == status)
        for status in ("PASS", "FAIL", "REJECTED")
    }
    return {
        "total": len(reports),
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "rejected": counts["REJECTED"],
        "pass_rate": counts["PASS"] / len(reports) if reports else 0.0,
    }
