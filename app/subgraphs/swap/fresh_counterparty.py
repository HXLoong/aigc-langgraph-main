"""全新文本下单：LLM 召回交易对手，Dify 聚合规则校验后补全订单。"""
from __future__ import annotations

import json
from typing import Any

from app.extraction.fields import FieldRecord
from app.graph.business_params import validated_place_params
from app.graph.retry import io_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts import load_prompt
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.aggregate import apply_fresh_counterparty, unique_fresh_counterparty
from app.subgraphs.swap.models import SwapFreshCounterpartyOutput


def _user_from_state(state: AgentState) -> str:
    """渲染 fresh_counterparty.md 的 user 模板（规则文本住 .md，代码只供变量）。"""
    candidates = state.get("swap_counterparties") or []
    shortname_list = json.dumps(
        [{"sort": c.get("sort"), "shortName": c.get("shortName")} for c in candidates],
        ensure_ascii=False,
    )
    prompt = load_prompt("swap", "fresh_counterparty")
    return prompt.render_user(
        raw_content=state.get("raw_text") or "",
        shortname_list=shortname_list,
    )


SPEC = register(PromptSpec(
    category="swap",
    name="fresh_counterparty",
    output_model=SwapFreshCounterpartyOutput,
    inputs=("raw_text", "swap_counterparties"),
    user_builder=_user_from_state,
))


@io_node
async def swap_recognize_fresh_counterparty(state: AgentState) -> dict[str, Any]:
    """只消费原话及后端候选；只更新 place_params 中的交易对手名称。"""
    raw_text = state.get("raw_text") or ""
    candidates = state.get("swap_counterparties") or []
    place_params = state.get("place_params") or {}
    original_orders = place_params.get("orderList") or []
    orders = [dict(order) for order in original_orders]

    recall = None
    shortname = None
    exact_names = {
        c["shortName"].strip() for c in candidates
        if isinstance(c.get("shortName"), str) and c["shortName"].strip()
        and not c["shortName"].strip().isdigit() and c["shortName"].strip() in raw_text
    }
    records: dict[str, FieldRecord] = {}
    if not orders:
        reason = "no_orders"
    elif not candidates:
        reason = "no_candidates"
    elif len(exact_names) == 1:
        shortname = next(iter(exact_names))
        # An overwide extraction can contain the complete authorized name plus incidental text.
        # Only literal containment is repairable; a different explicit account remains a conflict.
        for order in orders:
            existing = order.get("placeOrderShortname")
            if isinstance(existing, str) and shortname in existing and existing in raw_text:
                order["placeOrderShortname"] = shortname
        reason = apply_fresh_counterparty(orders, shortname)
    else:
        messages, _prompt_name = SPEC.build_messages(state)
        llm = get_qwen_complex().with_structured_output(SwapFreshCounterpartyOutput)
        result: Any = await llm.ainvoke(messages)
        recall = result.model_dump()
        shortname, reason = unique_fresh_counterparty(recall, candidates, raw_text)
        if shortname is not None:
            reason = apply_fresh_counterparty(orders, shortname)

    if reason == "applied" and shortname is not None:
        for index in range(len(orders)):
            records[f"swap/place_order.orderList.{index}.placeOrderShortname"] = FieldRecord(
                value=shortname, source="goats", evidence=shortname,
                origin="authorized-counterparties", locked=True,
            )

    affected_orders = [
        i for i, (before, after) in enumerate(zip(original_orders, orders, strict=True))
        if before.get("placeOrderShortname") != after.get("placeOrderShortname")
    ]
    return {
        "place_params": validated_place_params(**{**place_params, "orderList": orders}),
        "field_records": records,
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
