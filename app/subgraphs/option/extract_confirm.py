"""option.extract_confirm 节点 · 期权确认订单号提取（3 个 confirm 合并版）。

合并 3 个意图（共用 schema，靠 expected_action 区分）：
- confirm_order
- confirm_cancel_order
- confirm_modify_order

输入：raw_text + quote_content + history_messages
输出：state['confirm'] = {action, orderList}

action 取值：
- "place"  → confirm_order
- "cancel" → confirm_cancel_order
- "modify" → confirm_modify_order

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_confirm.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionExtractConfirmParams


def _format_history(history: list[Message] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for msg in history:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    history_str = _format_history(state.get("history_messages"))
    return (
        f"用户消息：{raw_content}\n\n"
        f"引用消息：{quote_content}\n\n"
        f"历史对话：\n{history_str}"
    )


def _expected_action(intent: str | None) -> str:
    """根据 intent 推 expected_action（合并版 3 子意图）。"""
    if intent == "confirm_cancel_order":
        return "cancel"
    if intent == "confirm_modify_order":
        return "modify"
    return "place"  # confirm_order 或兜底


@safe_node
async def option_extract_confirm(state: AgentState) -> dict[str, Any]:
    """option.extract_confirm 节点（合并版）。"""
    prompt = load_prompt("option", "extract_confirm")
    llm = get_qwen_thinking().with_structured_output(
        OptionExtractConfirmParams
    )

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    intent = state.get("intent")
    action = _expected_action(intent)
    order_list = [item.model_dump() for item in result.orderList]
    backend = await call_option_backend(
        state,
        intent=intent or "confirm_order",
        order_list=order_list,
    )

    return {
        "confirm": validated_confirm(action=action, orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_confirm",
                decision=f"action={action},orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_confirm"]
