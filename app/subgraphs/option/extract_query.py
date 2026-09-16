"""option.extract_query 节点 · 期权订单状态查询参数提取（确定性，已去 LLM 化）。

Dify DSL v2 迁移（对应 `期权-节点-查询订单状态`，node_id=17793301774310）：
处理 query_order_status。原 LLM 调用的唯一任务是提取 Q- 订单号，改为
app/subgraphs/option/order_id.py 确定性提取（瘦身 P1）。行为约定 1:1 对照原提示词：
raw 或 quote 提到具体订单号则提取；均无 → orderId: null（下游接口会查询近期所有订单）。

输入：raw_text + quote_content
输出：state['query_filter'] = {orderList} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_query_filter
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.order_id import extract_for_query


@safe_node
async def option_extract_query(state: AgentState) -> dict[str, Any]:
    """option.extract_query 节点（query_order_status，确定性提取）。"""
    order_ids = extract_for_query(
        raw=state.get("raw_text"), quote=state.get("quote_content")
    )
    order_list = [{"orderId": order_id} for order_id in order_ids]
    order_count = sum(1 for item in order_list if item["orderId"])

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
                decision=f"deterministic,orders={order_count}",
            )
        ],
    }


__all__ = ["option_extract_query"]
