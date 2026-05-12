"""swap.confirm 节点 · 互换确认（合并版，3 个 confirm 意图共用）。

ADR 0001 D5：合并 confirm_order + confirm_cancel_order + confirm_modify_order
3 个原节点为 1 个 swap.confirm，靠 expected_action 区分。

输入：raw_text + quote_content + history_messages + intent
输出：state['confirm'] = {action, orderList}

action 取值：
- "place"  → confirm_order
- "cancel" → confirm_cancel_order
- "modify" → confirm_modify_order

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/confirm.md（合并版新写）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.models import SwapConfirmParams


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
        f"raw_content: {raw_content}\n\n"
        f"quote_content: {quote_content}\n\n"
        f"history_query_str:\n{history_str}"
    )


def _expected_action(intent: str | None) -> str:
    """根据 intent 推 expected_action（合并版 3 子意图）。

    - confirm_order → "place"
    - confirm_cancel_order → "cancel"
    - confirm_modify_order → "modify"
    """
    if intent == "confirm_cancel_order":
        return "cancel"
    if intent == "confirm_modify_order":
        return "modify"
    return "place"  # confirm_order 或兜底


@safe_node
async def swap_confirm(state: AgentState) -> dict[str, Any]:
    """swap.confirm 节点（合并版）。"""
    prompt = load_prompt("swap", "confirm")
    llm = get_qwen_thinking().with_structured_output(SwapConfirmParams)

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

    # action → SwapIntentionType 映射
    _ACTION_INTENT = {
        "place": "confirm_order",
        "cancel": "confirm_cancel_order",
        "modify": "confirm_modify_order",
    }
    backend = await call_swap_backend(
        state,
        intent=_ACTION_INTENT.get(action, "confirm_order"),
        order_list=order_list,
    )

    return {
        "confirm": {
            "action": action,
            "orderList": order_list,
        },
        **backend,
        "trace": [
            TraceEntry(
                node="swap_confirm",
                decision=f"action={action},orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_confirm"]
