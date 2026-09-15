"""option.extract_cancel 节点 · 期权撤单订单号提取（请求撤单）。

Dify DSL v2 迁移（对应 `期权-节点-撤单请求`，node_id=17793301778710）：仅处理
request_cancel_order（针对已正式送出订单的撤单请求）。原 cancel_order_request
（取消下单，未正式送出阶段作废）已拆到独立节点 `extract_cancel_place`。

输入：raw_text + quote_content + history_messages
输出：state['cancel_params'] = {expected_action: "request_cancel", orderList}

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_cancel.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionCancelParams
from app.subgraphs.option.prompting import EXTRACT_INPUTS, extract_user
from app.subgraphs.option.sanitize import sanitize_order_list

SPEC = register(PromptSpec(
    category="option",
    name="extract_cancel",
    output_model=OptionCancelParams,
    inputs=EXTRACT_INPUTS,
    user_builder=extract_user,
))


@safe_node
async def option_extract_cancel(state: AgentState) -> dict[str, Any]:
    """option.extract_cancel 节点（request_cancel_order）。"""
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(OptionCancelParams)
    result: Any = await llm.ainvoke(messages)

    order_list = sanitize_order_list([item.model_dump() for item in result.order_list])
    backend = await call_option_backend(
        state,
        intent="request_cancel_order",
        order_list=order_list,
    )

    return {
        "cancel_params": validated_cancel_params(
            expected_action="request_cancel", orderList=order_list
        ),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_cancel",
                decision=f"action=request_cancel,orders={len(result.order_list)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_cancel"]
