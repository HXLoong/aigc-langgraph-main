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

from app.graph.business_params import validated_confirm
from app.graph.memory import memory_order_ids
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionConfirmPlaceParams
from app.subgraphs.option.place_params import (
    OrderScopeError,
    parse_place_params_with_lineage,
)
from app.subgraphs.option.provenance import prepare_order_provenance, use_memory_orders


@safe_node
async def option_extract_confirm_place(state: AgentState) -> dict[str, Any]:
    """option.extract_confirm_place 节点（confirm_order）。"""
    try:
        parsed = parse_place_params_with_lineage(
            state.get("raw_text"),
            state.get("quote_content"),
            state.get("history_messages") or [],
            confirm=True,
        )
    except OrderScopeError as exc:
        return {"reply_text": str(exc), "trace": [TraceEntry(
            node="option_extract_confirm_place", decision="order_scope_unresolved",
        )]}
    if parsed.orders and all(item.get("order_id") is None for item in parsed.orders):
        # 裸确认下单 → 上一轮询价卡记下的单号（ADR 0024 D4）；引用卡里的单号已在 parsed 里优先
        remembered = memory_order_ids(state, "option")
        if remembered:
            use_memory_orders(parsed, remembered)
    validated = OptionConfirmPlaceParams.model_validate({"orderList": parsed.orders})
    order_list = [item.model_dump() for item in validated.order_list]

    prepared_state, order_list, records = prepare_order_provenance(
        state, parsed, order_list, scope="option/confirm_place",
    )
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
