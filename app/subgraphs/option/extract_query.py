"""option.extract_query 节点 · 期权订单状态查询参数提取。

输入：raw_text + quote_content
输出：state['query_filter'] = {orderList}

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_query.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionExtractQueryParams
from app.graph.business_params import validated_query_filter


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


@safe_node
async def option_extract_query(state: AgentState) -> dict[str, Any]:
    """option.extract_query 节点。"""
    prompt = load_prompt("option", "extract_query")
    llm = get_qwen_thinking().with_structured_output(OptionExtractQueryParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )
    order_list = [item.model_dump() for item in result.orderList]
    backend = await call_option_backend(
        state,
        intent="query_order_status",
        order_list=order_list,
    )

    return {
        "query_filter": validated_query_filter(orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_query",
                decision=f"orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_query"]
