"""option.extract_confirm_place 节点 · 期权确认下单参数提取（确定性，无 LLM）。

Dify DSL v2 迁移新增节点（对应 `期权-节点-确认下单`，node_id=17793301761160），
从原 `extract_confirm`（confirm_order + confirm_cancel_order + confirm_modify_order
三合一）拆出，仅处理 confirm_order。

用户确认下单的同时可能补充建仓参数（确认下单后端会按需扭转为请求下单流程），
故与 extract_place 一样提取完整 orderList，而非仅 orderId。

2026-09 去 LLM 化：参数提取规约下沉到 `place_params.py` 确定性解析
（原 `app/prompts/option/extract_confirm_place.md` 已删除），输出仍经
`OptionConfirmPlaceParams` 校验补齐完整字段集。

输入：raw_text + quote_content + history_messages
输出：state['confirm'] = {action: "place", orderList}
"""
from __future__ import annotations

from typing import Any

from app.domain.confirmation import parse_confirmation
from app.domain.tenor import TenorError
from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionConfirmPlaceParams
from app.subgraphs.option.place_params import (
    OrderScopeError,
    parse_place_params_with_lineage,
)
from app.subgraphs.option.provenance import prepare_order_provenance


@safe_node
async def option_extract_confirm_place(state: AgentState) -> dict[str, Any]:
    """option.extract_confirm_place 节点（confirm_order）。"""
    confirmation = parse_confirmation(
        state.get("raw_text"), state.get("quote_content"), product="option", allow_parameters=True,
    )
    if confirmation.error:
        return {"confirm": None, "reply_text": confirmation.correction(),
                "trace": [TraceEntry(node="option_extract_confirm_place", decision=f"confirmation:{confirmation.error}")]}
    try:
        parsed = parse_place_params_with_lineage(
            state.get("raw_text"),
            state.get("quote_content"),
            state.get("history_messages") or [],
            confirm=True, selected_order_ids=confirmation.order_ids,
        )
    except (OrderScopeError, TenorError) as exc:
        return {"reply_text": str(exc), "trace": [TraceEntry(
            node="option_extract_confirm_place", decision="order_scope_unresolved",
        )]}
    selected = [(order, fields) for order, fields in zip(parsed.orders, parsed.fields, strict=True)
                if order.get("order_id") in confirmation.order_ids]
    parsed.orders = [order for order, _ in selected]
    parsed.fields = [fields for _, fields in selected]
    if {order["order_id"] for order in parsed.orders} != set(confirmation.order_ids):
        return {"reply_text": "无法确定确认订单范围，请重新引用订单消息。"}
    validated = OptionConfirmPlaceParams.model_validate({"orderList": parsed.orders})
    order_list = [item.model_dump() for item in validated.order_list]

    prepared_state, order_list, records = prepare_order_provenance(
        state, parsed, order_list, scope="option/confirm_place",
    )
    confirmation.verify_scope([order.get("orderId") for order in order_list])
    backend = await call_option_backend(
        prepared_state,
        intent="confirm_order",
        order_list=order_list,
    )

    return {
        "field_records": records,
        "expected_action": "place",
        "confirm": validated_confirm(action="place", orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_confirm_place",
                decision=f"deterministic,action=place,orders={len(order_list)}",
            )
        ],
    }


__all__ = ["option_extract_confirm_place"]
