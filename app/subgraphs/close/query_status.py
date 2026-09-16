"""close.query_status 节点 · 平仓订单状态查询参数提取（确定性，已去 LLM 化）。

原 LLM 调用的唯一任务是提取 CO- 订单号，改为 app/subgraphs/close/order_id.py
确定性提取（瘦身 P1）。行为约定 1:1 对照原提示词：仅从 raw 提取全部单号
（去重、统一大写）；均无 → []。原提示词 app/prompts/option_close/query_status.md
已同批删除。

输入：raw_text（用户提到的订单号列表）
输出：state['query_filter'] = {queryOrderNoList: [...]} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_query_filter
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.order_id import extract_for_query


@safe_node
async def close_query_status(state: AgentState) -> dict[str, Any]:
    """close.query_status 节点（确定性提取）。"""
    order_nos = extract_for_query(state.get("raw_text"))

    req_vo = build_close_order_req_vo(query_order_no_list=order_nos)
    backend = await call_close_backend(
        state,
        intent="close_order_order_query",
        close_order_req_vo=req_vo,
    )

    return {
        "query_filter": validated_query_filter(queryOrderNoList=order_nos),
        **backend,
        "trace": [
            TraceEntry(
                node="close_query_status",
                decision=f"deterministic,orders={len(order_nos)}",
            )
        ],
    }


__all__ = ["close_query_status"]
