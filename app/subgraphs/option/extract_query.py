"""option.extract_query 节点 · 期权订单状态查询参数提取。

Dify DSL v2 迁移（对应 `期权-节点-查询订单状态`，node_id=17793301774310）：
处理 query_order_status。

输入：raw_text + quote_content
输出：state['query_filter'] = {orderList}

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option/extract_query.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_query_filter
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionQueryParams
from app.subgraphs.option.prompting import EXTRACT_INPUTS, extract_user
from app.subgraphs.option.sanitize import sanitize_order_list

SPEC = register(PromptSpec(
    category="option",
    name="extract_query",
    output_model=OptionQueryParams,
    inputs=EXTRACT_INPUTS,
    user_builder=extract_user,
))


@safe_node
async def option_extract_query(state: AgentState) -> dict[str, Any]:
    """option.extract_query 节点。"""
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(OptionQueryParams)
    result: Any = await llm.ainvoke(messages)
    order_list = sanitize_order_list([item.model_dump() for item in result.order_list])
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
                decision=f"orders={len(result.order_list)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["option_extract_query"]
