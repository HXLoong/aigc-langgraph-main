"""swap.query_order 节点 · 互换订单状态查询(确定性,已去 LLM 化)。

瘦身 P1(docs/swap-prompt-slimming-assessment.md 病灶 2):原 LLM 调用的唯一
任务是提取 H- 订单号,改为确定性提取。原提示词 app/prompts/swap/query_order.md
已删除(零加载点即删,ADR 0022)。行为约定 1:1 对照原提示词:raw 优先,否则 quote。

输入:raw_text + quote_content
输出:state['query_filter'] = {orderList} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_query_filter
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.order_id import extract_for_query


@safe_node
async def swap_query_order(state: AgentState) -> dict[str, Any]:
    """swap.query_order 节点(确定性提取)。"""
    order_ids = extract_for_query(
        raw=state.get("raw_text"), quote=state.get("quote_content")
    )
    order_list = [{"orderId": oid} for oid in order_ids]

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
                decision=f"deterministic,orders={len(order_list)}",
            )
        ],
    }


__all__ = ["swap_query_order"]
