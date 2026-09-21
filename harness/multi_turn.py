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

from harness.golden import GoldenCase, TurnSpec

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


@dataclass
class MultiTurnResult:
    case_id: str
    conversation_id: str
    turns: list[TurnOutcome] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    remaining_turns: int = 0
    final_outputs: dict[str, Any] = field(default_factory=dict)


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
    reply = str(outputs.get("reply_text") or "")
    return TurnOutcome(
        index=index,
        scene=spec.scene,
        send_text=spec.send_text,
        at_bot=spec.at_bot,
        quote_passed=quote[:120],
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
) -> MultiTurnResult:
    conversation_id = f"ai-test-{uuid.uuid4().hex}"
    owned_client = client is None
    http_client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
    result = MultiTurnResult(case_id=case.id, conversation_id=conversation_id)
    try:
        for index, spec in enumerate(case.turns):
            if index and turn_interval:
                await asyncio.sleep(turn_interval)
            quote = quote_for_turn(
                index, spec.quote_previous, [turn.reply_text for turn in result.turns]
            )
            inputs = {
                "raw_text": spec.send_text,
                "message_content": spec.send_text,
                "message_id": secrets.randbelow(900_000_000_000_000) + 100_000_000_000_000,
                "user_id": user_id,
                "room_id": room_id,
                "quote_content": quote,
                "at_bot": spec.at_bot,
                "conversation_id": conversation_id,
            }
            endpoint = f"{base_url.rstrip('/')}/v1/workflows/run"
            if before_turn is not None:
                await before_turn(inputs)
            started = time.perf_counter()
            response = await http_client.post(
                endpoint,
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
            outcome = _extract_turn(index + 1, spec, quote, outputs)
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
            "kind": "technical_error",
            "error": {"type": type(exc).__name__, "message": str(exc)[:200]},
        }
        result.remaining_turns = len(case.turns) - len(result.turns)
    finally:
        if owned_client:
            await http_client.aclose()
    return result
