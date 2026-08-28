"""option.extract_confirm_place 节点 · 期权确认下单参数提取。

Dify DSL v2 迁移新增节点（对应 `期权-节点-确认下单`，node_id=17793301761160），
从原 `extract_confirm`（confirm_order + confirm_cancel_order + confirm_modify_order
三合一）拆出，仅处理 confirm_order。

用户确认下单的同时可能补充建仓参数（确认下单后端会按需扭转为请求下单流程），
故与 extract_place 一样提取完整 orderList，而非仅 orderId。

输入：raw_text + quote_content + history_messages
输出：state['confirm'] = {action: "place", orderList}

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_confirm_place.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionConfirmPlaceParams
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
async def option_extract_confirm_place(state: AgentState) -> dict[str, Any]:
    """option.extract_confirm_place 节点（confirm_order）。"""
    prompt = load_prompt("option", "extract_confirm_place")
    llm = get_qwen_thinking().with_structured_output(OptionConfirmPlaceParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    order_list = sanitize_order_list([item.model_dump() for item in result.orderList])
    backend = await call_option_backend(
        state,
        intent="confirm_order",
        order_list=order_list,
    )

    return {
        "confirm": validated_confirm(action="place", orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_confirm_place",
                decision=f"action=place,orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_confirm_place"]
