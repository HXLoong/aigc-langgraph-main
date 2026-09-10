"""option.extract_cancel_place 节点 · 期权取消下单订单号提取。

Dify DSL v2 迁移新增节点（对应 `期权-节点-取消下单`，node_id=17793301887260），
从原 `extract_cancel`（cancel_order_request + request_cancel_order 合并版）拆出，
仅处理 cancel_order_request（订单未正式送出阶段的作废）。

输入：raw_text + quote_content
输出：state['cancel_params'] = {expected_action: "cancel_request", orderList}

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_cancel_place.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionCancelPlaceParams
from app.subgraphs.option.sanitize import sanitize_order_list


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
async def option_extract_cancel_place(state: AgentState) -> dict[str, Any]:
    """option.extract_cancel_place 节点（cancel_order_request）。"""
    prompt = load_prompt("option", "extract_cancel_place")
    llm = get_qwen_thinking().with_structured_output(OptionCancelPlaceParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    order_list = sanitize_order_list([item.model_dump() for item in result.order_list])
    backend = await call_option_backend(
        state,
        intent="cancel_order_request",
        order_list=order_list,
    )

    return {
        "cancel_params": validated_cancel_params(
            expected_action="cancel_request", orderList=order_list
        ),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_cancel_place",
                decision=f"action=cancel_request,orders={len(result.order_list)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_cancel_place"]
