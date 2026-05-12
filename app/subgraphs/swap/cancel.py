"""swap.cancel 节点 · 互换撤单订单号提取。

输入：raw_text + quote_content + history_messages
输出：state['cancel_params'] = {orderList}

注：ADR 0001 D6 列了 swap.cancel + swap.cancel_extract 两个节点。骨架阶段
合并为单节点 swap.cancel —— swap.intent 已做意图分类，不需要额外的"路由层"
cancel.py。如果未来出现需要拆分的业务（如双阶段确认），再单独 PR 扩展。

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/cancel_order.md（Dify 原文）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.models import SwapCancelParams


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


@safe_node
async def swap_cancel(state: AgentState) -> dict[str, Any]:
    """swap.cancel 节点。"""
    prompt = load_prompt("swap", "cancel_order")
    llm = get_qwen_thinking().with_structured_output(SwapCancelParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    order_list = [item.model_dump() for item in result.orderList]
    backend = await call_swap_backend(
        state,
        intent="cancel_order_request",
        order_list=order_list,
    )

    return {
        "cancel_params": {
            "orderList": order_list,
        },
        **backend,
        "trace": [
            TraceEntry(
                node="swap_cancel",
                decision=f"orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_cancel"]
