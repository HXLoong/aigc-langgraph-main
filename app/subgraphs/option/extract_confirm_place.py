"""期权确认：校验本次动作和选择，只提交订单号及显式增量。"""
from __future__ import annotations

from typing import Any

from app.domain.confirmation import parse_confirmation
from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import prepare_option_request
from app.subgraphs.option.request_params import request_orders


@safe_node
async def option_extract_confirm_place(state: AgentState) -> dict[str, Any]:
    """用户明确确认后提交本次参数，不读取历史中的完整订单。"""
    # 1. 动作与订单选择一致，否定、疑问和范围歧义不会被提升为确认。
    confirmation = parse_confirmation(state.get("raw_text"), state.get("quote_content"),
                                      product="option", allow_parameters=True)
    if confirmation.error:
        return {"confirm": None, "reply_text": confirmation.correction(),
                "trace": [TraceEntry(node="option_extract_confirm_place", decision=f"confirmation:{confirmation.error}")]}
    orders, records = request_orders(state, "confirm_order")
    confirmation.verify_scope([order.get("orderId") for order in orders])
    # 2. 仅携带这一次提供的字段；已有订单由 Java 读取、合并和执行。
    prepared: AgentState = {**state, "field_records": {**(state.get("field_records") or {}), **records}}
    request_update = await prepare_option_request(prepared, intent="confirm_order", order_list=orders)
    return {"field_records": records, "expected_action": "place",
            "confirm": validated_confirm(action="place", orderList=orders), **request_update,
            "trace": [TraceEntry(node="option_extract_confirm_place", decision=f"orders={len(orders)}")]}
