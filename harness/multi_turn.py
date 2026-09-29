"""HTTP multi-turn runner for the Dify-compatible LangGraph endpoint."""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from harness.golden import GoldenCase, TurnSpec, dataset_expected, dataset_input
from harness.langfuse_client import case_trace, http_turn_trace
from harness.scenario_inputs import (
    ScenarioInputError,
    ensure_execution_window,
    resolve_order_reference,
)

_BACKEND_ERROR_MARKERS = ("正在处理", "请勿重复", "未授权", "失败：未补充")


@dataclass
class TurnOutcome:
    index: int
    scene: str
    send_text: str
    at_bot: bool
    quote_passed: str
    reply_text: str
    product_type: str | None
    intent: str | None
    tickers: list[dict[str, Any]]
    place_params: dict[str, Any] | None
    api_code: int | None
    api_result: Any
    error: dict[str, Any] | None
    trace: str
    outputs: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    quote_content: str = ""


@dataclass
class MultiTurnResult:
    case_id: str
    conversation_id: str
    turns: list[TurnOutcome] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    remaining_turns: int = 0
    final_outputs: dict[str, Any] = field(default_factory=dict)
    langfuse_trace_id: str | None = None
    observation_id: str | None = None
    trace_status: str = "disabled"


def is_unusable_quote(text: str) -> bool:
    """后端短错误消息（dedup / 限流 / 授权失败）不能作为下轮 quote。"""
    return bool(text) and len(text) <= 200 and any(marker in text for marker in _BACKEND_ERROR_MARKERS)


def quote_for_turn(index: int, quote_previous: bool | None, prev_replies: list[str]) -> str:
    """挑选第 index 轮 quote：False 或首轮为空；True 自上一轮回溯；None 取第 1 轮回复。"""
    if index == 0 or quote_previous is False:
        return ""
    candidates = reversed(prev_replies) if quote_previous is True else prev_replies[:1]
    for reply in candidates:
        if reply and not is_unusable_quote(reply):
            return reply
    return ""


def early_stop_kind(has_error: bool, api_code: object) -> str | None:
    """早停谓词：节点错误优先；后端业务拒绝仅认 int 且非 0。"""
    if has_error:
        return "node_error"
    if isinstance(api_code, int) and api_code != 0:
        return "business_reject"
    return None


def _error_info(value: Any) -> dict[str, Any] | None:
    """将节点错误投影到评测报告的稳定诊断字段。"""
    if not value:
        return None
    if isinstance(value, dict):
        return {
            "node": value.get("node"),
            "type": value.get("type"),
            "code": value.get("code"),
            "causes": value.get("causes") or [],
            "message": str(value.get("message") or "")[:200],
        }
    return {"node": None, "type": type(value).__name__, "message": str(value)[:200]}


def _extract_turn(index: int, spec: TurnSpec, quote: str, outputs: dict[str, Any]) -> TurnOutcome:
    """保留每轮真实输入、HTTP 输出、业务参数与追踪身份。"""
    reply = str(outputs.get("reply_text") or "")
    return TurnOutcome(
        index=index,
        scene=spec.scene,
        send_text=spec.send_text,
        at_bot=spec.at_bot,
        quote_passed=quote[:120],
        quote_content=quote,
        reply_text=reply,
        product_type=outputs.get("product_type"),
        intent=outputs.get("intent"),
        tickers=list(outputs.get("tickers") or []),
        place_params=outputs.get("place_params"),
        api_code=outputs.get("api_code"),
        api_result=outputs.get("api_result"),
        error=_error_info(outputs.get("error")),
        trace=str(outputs.get("trace") or ""),
        outputs=outputs,
    )


async def run_case_multi(
    case: GoldenCase,
    *,
    base_url: str,
    user_id: str,
    room_id: str,
    turn_interval: float = 0.0,
    timeout: float = 180.0,
    client: httpx.AsyncClient | None = None,
    before_turn: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    trace_metadata: dict[str, Any] | None = None,
) -> MultiTurnResult:
    """执行完整用例；会话 ID 先于根 Observation 创建，多轮共用一棵树。"""
    conversation_id = f"ai-test-{uuid.uuid4().hex}"
    with case_trace(case.id, conversation_id, user_id, metadata=trace_metadata,
                    case_input=dataset_input(case)) as trace:
        result = await _run_case_turns(
            case, conversation_id=conversation_id, base_url=base_url, user_id=user_id,
            room_id=room_id, turn_interval=turn_interval, timeout=timeout, client=client,
            before_turn=before_turn,
        )
        # 保留每轮服务端 ID，核对实际接续结果，不以 SDK 初始化成功代替验证。
        result.langfuse_trace_id = trace.trace_id
        result.observation_id = trace.observation_id
        if trace.trace_id:
            connected = bool(result.turns) and all(
                turn.outputs.get("langfuse_trace_id") == trace.trace_id for turn in result.turns
            )
            result.trace_status = "complete" if connected and not result.remaining_turns else "incomplete"
        trace.update({"case_id": case.id, "expected": dataset_expected(case), "turns": [turn.outputs for turn in result.turns],
                      "failure": result.failure, "trace_status": result.trace_status})
        return result


async def _run_case_turns(
    case: GoldenCase, *, conversation_id: str, base_url: str, user_id: str, room_id: str,
    turn_interval: float, timeout: float, client: httpx.AsyncClient | None,
    before_turn: Callable[[dict[str, Any]], Awaitable[None]] | None,
) -> MultiTurnResult:
    """按序执行各轮，保留真实引用、失败轮和未执行轮数。"""
    owned_client = client is None
    http_client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
    result = MultiTurnResult(case_id=case.id, conversation_id=conversation_id)
    try:
        ensure_execution_window(case.execution_before)
        for index, spec in enumerate(case.turns):
            resolved_text = resolve_order_reference(
                spec.send_text, result.turns[-1].reply_text if result.turns else ""
            )
            delay = max(turn_interval if index else 0, spec.wait_before_seconds)
            if delay:
                await asyncio.sleep(delay)
            # 明确冻结的引用属于本轮输入，不能被空值或自动引用替换。
            quote = spec.quote_content or quote_for_turn(
                index, spec.quote_previous, [turn.reply_text for turn in result.turns]
            )
            inputs = {
                "raw_text": resolved_text,
                "message_content": resolved_text,
                "message_id": secrets.randbelow(900_000_000_000_000) + 100_000_000_000_000,
                "user_id": user_id,
                "room_id": room_id,
                "quote_content": quote,
                "at_bot": spec.at_bot,
                "fast_query": spec.fast_query,
                "conversation_id": conversation_id,
            }
            endpoint = f"{base_url.rstrip('/')}/v1/workflows/run"
            if before_turn is not None:
                await before_turn(inputs)
            started = time.perf_counter()
            with http_turn_trace(index + 1) as trace_headers:
                response = await http_client.post(
                    endpoint, headers=trace_headers,
                    json={
                        "conversation_id": conversation_id,
                        "inputs": inputs,
                        "response_mode": "blocking",
                        "user": user_id,
                    },
                )
                response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            outputs = dict(data.get("outputs") or {})
            if data.get("status") != "succeeded" and not outputs.get("error"):
                outputs["error"] = data.get("error") or data.get("status")
            resolved_spec = spec.model_copy(update={"send_text": resolved_text})
            outcome = _extract_turn(index + 1, resolved_spec, quote, outputs)
            outcome.elapsed_ms = int((time.perf_counter() - started) * 1000)
            result.turns.append(outcome)
            result.final_outputs = outputs
            kind = early_stop_kind(outcome.error is not None, outcome.api_code)
            if kind is not None:
                failure: dict[str, Any] = {
                    "turn": index + 1,
                    "kind": kind,
                    "api_code": outcome.api_code,
                    "api_result": outcome.api_result,
                }
                if outcome.error is not None:
                    failure["error"] = outcome.error
                result.failure = failure
                result.remaining_turns = len(case.turns) - len(result.turns)
                break
    except (httpx.HTTPError, ValueError) as exc:
        result.failure = {
            "turn": len(result.turns) + 1,
            "kind": "fixture_precondition" if isinstance(exc, ScenarioInputError) else "technical_error",
            "error": {"type": type(exc).__name__, "message": str(exc)[:200]},
        }
        result.remaining_turns = len(case.turns) - len(result.turns)
    finally:
        if owned_client:
            await http_client.aclose()
    return result
