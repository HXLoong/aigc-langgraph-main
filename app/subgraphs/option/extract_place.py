"""option.extract_place 节点 · 期权请求下单参数提取（P0 核心）。

Dify DSL v2 迁移新增节点（对应 `期权-节点-下单`，node_id=17793301871440），
替代原 `extract_place_or_modify`（合并版）。期权无独立改单流程——用户对已有
Q- 订单的参数修改请求，intent 节点统一归为 `place_order_from_quote`，仍由本
节点处理（见 `app/prompts/option/intent.md` 规则1第7条）。

输入：raw_text + quote_content + history_messages
输出：state['place_params'] = {expected_action: "place", orderList}

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_place.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionPlaceParams
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
async def option_extract_place(state: AgentState) -> dict[str, Any]:
    """option.extract_place 节点。

    出参约定：
    - place_params: dict 含 expected_action="place" + orderList
    - trace: 单条 TraceEntry，记录订单数 + orderType 分布
    """
    prompt = load_prompt("option", "extract_place")
    llm = get_qwen_thinking().with_structured_output(OptionPlaceParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    types = [item.orderType for item in result.orderList if item.orderType]
    order_list = sanitize_order_list([item.model_dump() for item in result.orderList])
    decision = f"action=place, orders={len(result.orderList)}, types={types}"
    backend = await call_option_backend(
        state,
        intent="place_order_from_quote",
        order_list=order_list,
    )

    return {
        "place_params": validated_place_params(expected_action="place", orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_place",
                decision=decision,
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_place"]
