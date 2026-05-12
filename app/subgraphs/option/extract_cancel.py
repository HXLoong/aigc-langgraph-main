"""option.extract_cancel 节点 · 期权撤单订单号提取。

合并 2 个意图：
- cancel_order_request（取消下单请求）
- request_cancel_order（请求撤单）

输入：raw_text + quote_content + history_messages
输出：state['cancel_params'] = {expected_action, orderList}

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_cancel.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionExtractCancelParams


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
    """根据 intent 推 expected_action：
    - cancel_order_request → "cancel_request"（取消下单请求）
    - request_cancel_order → "request_cancel"（请求撤单已下订单）
    - 其他 → "cancel_request"（兜底）
    """
    if intent == "request_cancel_order":
        return "request_cancel"
    return "cancel_request"


@safe_node
async def option_extract_cancel(state: AgentState) -> dict[str, Any]:
    """option.extract_cancel 节点。"""
    prompt = load_prompt("option", "extract_cancel")
    llm = get_qwen_structured().with_structured_output(OptionExtractCancelParams)

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
        intent=intent or "cancel_order_request",
        order_list=order_list,
    )

    return {
        "cancel_params": {
            "expected_action": action,
            "orderList": order_list,
        },
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_cancel",
                decision=f"action={action},orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_cancel"]
