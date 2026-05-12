"""swap.query_order 节点 · 互换订单状态查询参数提取。

输入：raw_text + quote_content + history_messages
输出：state['query_filter'] = {orderList}

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/query_order.md（Dify 原文）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.swap.models import SwapQueryParams


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
async def swap_query_order(state: AgentState) -> dict[str, Any]:
    """swap.query_order 节点。"""
    prompt = load_prompt("swap", "query_order")
    llm = get_qwen_thinking().with_structured_output(SwapQueryParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    return {
        "query_filter": {
            "orderList": [item.model_dump() for item in result.orderList],
        },
        "trace": [
            TraceEntry(
                node="swap_query_order",
                decision=f"orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_query_order"]
