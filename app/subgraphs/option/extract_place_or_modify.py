"""option.extract_place_or_modify 节点 · 期权下单/改单参数提取（P0 核心）。

输入：raw_text + quote_content + history_messages
输出：state['place_params'] = {orderList, expected_action}

骨架阶段范围：
- LLM 提取 orderList（每元素 8 字段）
- expected_action 由 intent 推导（place_order_from_quote → "place_or_quote_fill"，
  request_modify_order → "modify"）
- **本节点不需要 ticker resolver**——标的已在 Q- 询价单中确定

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_place_or_modify.md（拆分后的轻量版）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionPlaceOrModifyParams


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


def _expected_action_from_intent(intent: str | None) -> str:
    """根据 intent 推导 expected_action（同 swap.confirm 合并版同款约定）。

    - place_order_from_quote → "place"
    - request_modify_order → "modify"
    - 其他 → "place"（兜底）
    """
    if intent == "request_modify_order":
        return "modify"
    return "place"


@safe_node
async def option_extract_place_or_modify(state: AgentState) -> dict[str, Any]:
    """option.extract_place_or_modify 节点。

    出参约定：
    - place_params: dict 含 expected_action + orderList
    - trace: 单条 TraceEntry，记录订单数 + orderType 分布
    """
    prompt = load_prompt("option", "extract_place_or_modify")
    llm = get_qwen_thinking().with_structured_output(OptionPlaceOrModifyParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    intent = state.get("intent")
    expected_action = _expected_action_from_intent(intent)

    types = [item.orderType for item in result.orderList if item.orderType]
    order_list = [item.model_dump() for item in result.orderList]
    decision = (
        f"action={expected_action},"
        f" orders={len(result.orderList)},"
        f" types={types}"
    )
    backend = await call_option_backend(
        state,
        intent=intent or "place_order_from_quote",
        order_list=order_list,
    )

    return {
        "place_params": {
            "expected_action": expected_action,
            "orderList": order_list,
        },
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_place_or_modify",
                decision=decision,
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_place_or_modify"]
