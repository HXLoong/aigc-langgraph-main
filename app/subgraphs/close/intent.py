"""期权平仓意图：确定性规则优先，模型分支必须提供可校验证据与置信度。"""
from __future__ import annotations

import re
from typing import Any

from app.execution.confirmation import (
    confirmation_action,
    confirmation_attempt,
    has_execution_parameters,
)
from app.extraction.intent_evidence import intent_records, source_payload
from app.graph.retry import io_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.close.models import CloseIntentOutput


def _build_user_message(state: AgentState) -> str:
    return (
        f"raw_content: {state.get('raw_text', '') or ''}\n\n"
        f"quote_content: {state.get('quote_content') or ''}\n\n"
        f"history_query_str:\n{blocks.format_history(state.get('history_messages'))}"
    )


SPEC = register(PromptSpec(
    category="option_close",
    name="intent",
    output_model=CloseIntentOutput,
    inputs=("raw_text", "quote_content", "history_messages"),
    user_builder=lambda state: _build_user_message(state) + "\n" + source_payload(state),
))


def _deterministic_intent(raw: str) -> str | None:
    """Move unconditional corrections ahead of the model, preserving their precedence."""
    action = confirmation_action(raw)
    if confirmation_attempt(raw):
        if action == "close" and has_execution_parameters(raw):
            return "close_order_request"
        return {"close": "close_order_confirm", "cancel": "close_order_cancel_confirm"}.get(action or "", "unknown_intent")
    if any(kw in raw for kw in ("拉满跟量", "全部最大", "全跟量")) and re.search(r"\d+\s*万", raw):
        return "close_order_request"
    if re.search(r"序号\s*\d", raw) and any(kw in raw.lower() for kw in ("平", "留", "全平", "拉满", "跟量", "pov")):
        return "close_order_request"
    if "确认撤单" in raw:
        return "close_order_cancel_confirm"
    if any(kw in raw for kw in ("查可平持仓", "查询持仓", "我有哪些")):
        return "close_order_query"
    return None


@io_node
async def close_intent(state: AgentState) -> dict[str, Any]:
    """close.intent 节点。"""
    deterministic = _deterministic_intent(state.get("raw_text") or "")
    if deterministic:
        return {"intent": deterministic, "trace": [TraceEntry(
            node="close_intent", decision=f"intent={deterministic} rule=explicit_instruction",
        )]}
    # ADR 0023：输出契约由 with_structured_output 的 schema 承担，不再在代码里追加格式指令
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(CloseIntentOutput)
    result = CloseIntentOutput.model_validate(await llm.ainvoke(messages))
    records = intent_records(result, state, scope="close/intent", value=result.type)

    intent = result.type
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    text = f"{raw} {quote}"

    # 规则修正：含合约编号+平仓动作词但 LLM 误分为 query → request
    if intent == "close_order_query":
        has_contract = bool(re.search(r"(?:OPT|OPTG)-\w+", text))
        close_actions = ("平掉","平仓","平剩","平留","市价平","部分平","我想平","我要平")
        if has_contract and any(a in text for a in close_actions):
            intent = "close_order_request"
    # "撤单" 关键词 → close_order_cancel_request（覆盖 LLM 误判）
    if "撤单" in raw and intent not in (
        "close_order_cancel_confirm", "close_order_cancel_request"
    ):
        intent = "close_order_cancel_request"
    if intent != result.type:
        records["close/intent.model"] = records["close/intent"]
        records["close/intent"] = records["close/intent"].model_copy(update={
            "value": intent, "source": "default", "confidence": None,
        })
    return {
        "field_records": records,
        "intent": intent,
        "trace": [
            TraceEntry(
                node="close_intent",
                decision=f"intent={intent}",
                llm_output={"type": intent, "model_type": result.type, "confidence": result.confidence, "evidence_count": len(result.evidence)},
            )
        ],
    }


__all__ = ["close_intent"]
