"""全新文本下单：LLM 召回交易对手，Dify 聚合规则校验后补全订单。"""
from __future__ import annotations

import json
from typing import Any

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts import load_prompt
from app.subgraphs.swap.aggregate import apply_fresh_counterparty, unique_fresh_counterparty
from app.subgraphs.swap.models import SwapFreshCounterpartyOutput


@safe_node
async def swap_recognize_fresh_counterparty(state: AgentState) -> dict[str, Any]:
    """只消费原话及后端候选；只更新 place_params 中的交易对手名称。"""
    raw_text = state.get("raw_text") or ""
    candidates = state.get("swap_counterparties") or []
    place_params = state.get("place_params") or {}
    original_orders = place_params.get("orderList") or []
    orders = [dict(order) for order in original_orders]

    recall = None
    shortname = None
    if not orders:
        reason = "no_orders"
    elif not candidates:
        reason = "no_candidates"
    else:
        prompt = load_prompt("swap", "fresh_counterparty")
        shortname_list = json.dumps(
            [{"sort": c.get("sort"), "shortName": c.get("shortName")} for c in candidates],
            ensure_ascii=False,
        )
        user_message = prompt.render_user(**{
            "#1755072621769.raw_content#": raw_text,
            "#1772773805306.trsShortListStr#": shortname_list,
        })
        llm = get_qwen_complex().with_structured_output(SwapFreshCounterpartyOutput)
        result: Any = await llm.ainvoke([("system", prompt.system), ("user", user_message)])
        recall = result.model_dump()
        shortname, reason = unique_fresh_counterparty(recall, candidates, raw_text)
        if shortname is not None:
            reason = apply_fresh_counterparty(orders, shortname)

    affected_orders = [
        i for i, (before, after) in enumerate(zip(original_orders, orders, strict=True))
        if before.get("placeOrderShortname") != after.get("placeOrderShortname")
    ]
    return {
        "place_params": validated_place_params(**{**place_params, "orderList": orders}),
        "trace": [TraceEntry(
            node="swap_recognize_fresh_counterparty",
            decision=f"reason={reason},affected_orders={affected_orders}",
            llm_output={
                "recall": recall,
                "adopted": reason == "applied",
                "reason": reason,
                "shortname": shortname,
                "affected_orders": affected_orders,
            },
        )],
    }


__all__ = ["swap_recognize_fresh_counterparty"]
