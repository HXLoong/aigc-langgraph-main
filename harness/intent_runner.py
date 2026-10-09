"""冻结意图回归通过节点 HTTP 入口执行，不在评测进程内构建业务图。"""
from __future__ import annotations

import importlib
import uuid
from typing import Any

import httpx

from harness.golden import GoldenCase, TurnSpec, dataset_expected, dataset_input
from harness.intent_context import requires_replay
from harness.langfuse_client import case_trace, http_turn_trace
from harness.multi_turn import MultiTurnResult, _extract_turn

# 授权参考列表来自仓库 mock 数据，仅供隔离意图评测，不替生产查询结果。
COUNTERPARTIES: list[dict[str, Any]] = importlib.import_module("mock_api.backend.fixtures").COUNTERPARTIES


def turn_state(turn: TurnSpec, *, conversation_id: str) -> dict[str, Any]:
    """只投影输入和冻结上下文，expected 永不进入模型输入。"""
    state: dict[str, Any] = {
        "fast_query": turn.fast_query, "at_bot": turn.at_bot,
        "robot_version": turn.robot_version, "existing_command": turn.existing_command,
        "raw_text": turn.send_text, "quote_content": turn.quote_content,
        "conversation_id": conversation_id,
        "option_counterparties": COUNTERPARTIES, "swap_counterparties": COUNTERPARTIES,
        "history_messages": [dict(message) for message in turn.history],
    }
    if turn.prev_product_type:
        state["product_type"] = turn.prev_product_type
    return state


def _node_outputs(update: dict[str, Any], tracing: dict[str, Any]) -> dict[str, Any]:
    """将联合解析节点的输出投影到与业务回归相同的观察字段。"""
    parsed = update.get("parsed_instruction") or {}
    entries = update.get("trace") or []
    trace = " → ".join(f"{entry.get('node')}[{entry.get('decision') or ''}]" for entry in entries)
    result = {**update, **tracing, "trace": trace, "reply_text": update.get("reply_text") or ""}
    if "orders" in parsed and parsed.get("product_type") in {"option", "swap"}:
        result["place_params"] = {"orderList": parsed["orders"]}
    return result


async def run_frozen_case(
    case: GoldenCase, *, base_url: str, user_id: str,
    client: httpx.AsyncClient | None = None, timeout: float = 90,
    trace_metadata: dict[str, Any] | None = None,
) -> MultiTurnResult:
    """逐轮独立执行解析节点；某轮失败不改变其它轮冻结输入。"""
    conversation_id = f"ai-test-{uuid.uuid4().hex}"
    result = MultiTurnResult(case.id, conversation_id)
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        with case_trace(case.id, conversation_id, user_id, metadata=trace_metadata,
                    case_input=dataset_input(case)) as trace:
            for index, turn in enumerate(case.turns, 1):
                try:
                    state = turn_state(turn, conversation_id=conversation_id)
                    # 快速样例只验真实入口节点，普通冻结样例仍执行唯一解析器。
                    node = "entry_route" if turn.fast_query == "1" else "parse_instruction"
                    with http_turn_trace(index) as headers:
                        response = await http.post(f"{base_url.rstrip('/')}/v1/nodes/run", headers=headers,
                            json={"product": "main", "node": node, "state": state})
                    body = response.json()
                    # 节点错误响应仍保留自身 updates，不能因 HTTP 500 丢掉归因信息。
                    if "output" not in body:
                        response.raise_for_status()
                        raise ValueError("node response lacks output")
                    outputs = _node_outputs(body["output"], body.get("tracing") or {})
                    if outputs.get("error"):
                        result.failure = {"turn": index, "kind": "node_error", "error": outputs["error"]}
                except (httpx.HTTPError, ValueError) as exc:
                    outputs = {"error": {"type": type(exc).__name__, "message": str(exc)[:200]}}
                    result.failure = {"turn": index, "kind": "technical_error", "error": outputs["error"]}
                result.turns.append(_extract_turn(index, turn, turn.quote_content, outputs))
                result.final_outputs = outputs
            result.langfuse_trace_id, result.observation_id = trace.trace_id, trace.observation_id
            if trace.trace_id:
                result.trace_status = "complete" if result.turns and all(
                    turn.outputs.get("langfuse_trace_id") == trace.trace_id for turn in result.turns
                ) else "incomplete"
            trace.update({"expected": dataset_expected(case), "turns": [turn.outputs for turn in result.turns], "failure": result.failure})
    finally:
        if client is None:
            await http.aclose()
    return result


__all__ = ["requires_replay", "run_frozen_case", "turn_state"]
