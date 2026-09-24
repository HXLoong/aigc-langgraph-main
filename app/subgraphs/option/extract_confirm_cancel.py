"""期权确认撤单：校验明确口令及当前引用范围，再调用 Java。"""
from __future__ import annotations

from typing import Any

from app.domain.confirmation import parse_confirmation
from app.extraction.identity import prepare_identity_scope
from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend


@safe_node
async def option_extract_confirm_cancel(state: AgentState) -> dict[str, Any]:
    """option.extract_confirm_cancel 节点（confirm_cancel_order，确定性提取）。"""
    identity_origin = "quote"
    identity_evidence = state.get("quote_content") or ""
    confirmation = parse_confirmation(
        state.get("raw_text"), state.get("quote_content"), product="option", action="cancel",
    )
    if confirmation.error:
        return {"confirm": None, "reply_text": confirmation.correction(),
                "trace": [TraceEntry(node="option_extract_confirm_cancel", decision=f"confirmation:{confirmation.error}")]}
    order_ids: list[str | None] = list(confirmation.order_ids)
    prepared_state, order_ids, records = prepare_identity_scope(
        state, order_ids, scope="option/confirm_cancel", origin=identity_origin, evidence=identity_evidence, selection=True,
    )
    confirmation.verify_scope(order_ids)
    order_list = [{"orderId": order_id} for order_id in order_ids]
    order_count = sum(1 for item in order_list if item["orderId"])

    backend = await call_option_backend(
        prepared_state,
        intent="confirm_cancel_order",
        order_list=order_list,
    )

    return {
        "field_records": records,
        "expected_action": "cancel",
        "confirm": validated_confirm(action="cancel", orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_confirm_cancel",
                decision=f"deterministic,action=cancel,orders={order_count}",
            )
        ],
    }


__all__ = ["option_extract_confirm_cancel"]
