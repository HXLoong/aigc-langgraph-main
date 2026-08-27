"""swap.query_order 节点 · 互换订单状态查询参数提取。

输入：raw_text + quote_content
输出：state['query_filter'] = {orderList}

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/query_order.md（DSL v2 互换-节点-查询订单，2 变量：
raw_content / quote_content，不再含 history_query_str）。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_query_filter
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.models import SwapQueryParams


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return f"raw_content：{raw_content}\nquote_content：{quote_content}"


@safe_node
async def swap_query_order(state: AgentState) -> dict[str, Any]:
    """swap.query_order 节点。"""
    prompt = load_prompt("swap", "query_order")
    llm = get_qwen_thinking().with_structured_output(SwapQueryParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    order_list = [item.model_dump() for item in result.orderList]
    backend = await call_swap_backend(
        state,
        intent="query_order_status",
        order_list=order_list,
    )

    return {
        "query_filter": validated_query_filter(orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="swap_query_order",
                decision=f"orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_query_order"]
