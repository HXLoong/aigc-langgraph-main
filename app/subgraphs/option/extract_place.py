"""期权下单或补参：只提交本次联合解析给出的稀疏参数。"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import prepare_option_request
from app.subgraphs.option.request_params import request_orders


@safe_node
async def option_extract_place(state: AgentState) -> dict[str, Any]:
    """检查本次目标与来源，把已有订单的合并和业务校验留给 Java。"""
    orders, records = request_orders(state, "place_order_from_quote")
    # 来源账本先进入请求边界，实际提交字段保持锁定。
    prepared: AgentState = {**state, "field_records": {**(state.get("field_records") or {}), **records}}
    request_update = await prepare_option_request(prepared, intent="place_order_from_quote", order_list=orders)
    return {"field_records": records, "expected_action": "place",
            "place_params": validated_place_params(orderList=orders), **request_update,
            "trace": [TraceEntry(node="option_extract_place", decision=f"orders={len(orders)}")]}
