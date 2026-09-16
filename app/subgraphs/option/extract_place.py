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
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionPlaceParams
from app.subgraphs.option.prompting import EXTRACT_INPUTS, extract_user
from app.subgraphs.option.sanitize import sanitize_order_list

SPEC = register(PromptSpec(
    category="option",
    name="extract_place",
    output_model=OptionPlaceParams,
    inputs=EXTRACT_INPUTS,
    user_builder=extract_user,
))


@safe_node
async def option_extract_place(state: AgentState) -> dict[str, Any]:
    """option.extract_place 节点。

    出参约定：
    - place_params: dict 含 expected_action="place" + orderList
    - trace: 单条 TraceEntry，记录订单数 + orderType 分布
    """
    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(OptionPlaceParams)
    result: Any = await llm.ainvoke(messages)

    types = [item.order_type for item in result.order_list if item.order_type]
    order_list = sanitize_order_list([item.model_dump() for item in result.order_list])
    decision = f"action=place, orders={len(result.order_list)}, types={types}"
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
