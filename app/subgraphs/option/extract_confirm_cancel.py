"""option.extract_confirm_cancel 节点 · 期权确认撤单订单号提取。

Dify DSL v2 迁移新增节点（对应 `期权-节点-确认撤单`，node_id=17793301782150），
从原 `extract_confirm`（confirm_order + confirm_cancel_order + confirm_modify_order
三合一）拆出，仅处理 confirm_cancel_order。

输入：raw_text + quote_content
输出：state['confirm'] = {action: "cancel", orderList}

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_confirm_cancel.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionConfirmCancelParams
from app.subgraphs.option.prompting import EXTRACT_INPUTS, extract_user
from app.subgraphs.option.sanitize import sanitize_order_list

SPEC = register(PromptSpec(
    category="option",
    name="extract_confirm_cancel",
    output_model=OptionConfirmCancelParams,
    inputs=EXTRACT_INPUTS,
    user_builder=extract_user,
))


@safe_node
async def option_extract_confirm_cancel(state: AgentState) -> dict[str, Any]:
    """option.extract_confirm_cancel 节点（confirm_cancel_order）。"""
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(OptionConfirmCancelParams)
    result: Any = await llm.ainvoke(messages)

    order_list = sanitize_order_list([item.model_dump() for item in result.order_list])
    backend = await call_option_backend(
        state,
        intent="confirm_cancel_order",
        order_list=order_list,
    )

    return {
        "confirm": validated_confirm(action="cancel", orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_confirm_cancel",
                decision=f"action=cancel,orders={len(result.order_list)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_confirm_cancel"]
