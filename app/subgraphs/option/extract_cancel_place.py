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
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionCancelPlaceParams
from app.subgraphs.option.prompting import EXTRACT_INPUTS, extract_user
from app.subgraphs.option.sanitize import sanitize_order_list

SPEC = register(PromptSpec(
    category="option",
    name="extract_cancel_place",
    output_model=OptionCancelPlaceParams,
    inputs=EXTRACT_INPUTS,
    user_builder=extract_user,
))


@safe_node
async def option_extract_cancel_place(state: AgentState) -> dict[str, Any]:
    """option.extract_cancel_place 节点（cancel_order_request）。"""
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(OptionCancelPlaceParams)
    result: Any = await llm.ainvoke(messages)

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
