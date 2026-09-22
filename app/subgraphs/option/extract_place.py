"""option.extract_place 节点 · 期权请求下单参数提取（确定性，无 LLM）。

Dify DSL v2 迁移新增节点（对应 `期权-节点-下单`，node_id=17793301871440），
替代原 `extract_place_or_modify`（合并版）。期权无独立改单流程——用户对已有
Q- 订单的参数修改请求，intent 节点统一归为 `place_order_from_quote`，仍由本
节点处理（见 `app/prompts/option/intent.md` 规则1第7条）。

2026-09 去 LLM 化：参数提取规约下沉到 `place_params.py` 确定性解析
（原 `app/prompts/option/extract_place.md` 已删除），输出仍经
`OptionPlaceParams` 校验补齐完整字段集。

输入：raw_text + quote_content + history_messages
输出：state['expected_action'] = "place" + state['place_params'] = {orderList}
"""
from __future__ import annotations

from typing import Any

from app.extraction.tenor import TenorError
from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.models import OptionPlaceParams
from app.subgraphs.option.place_params import OrderScopeError, parse_place_params_with_lineage
from app.subgraphs.option.provenance import prepare_order_provenance


@safe_node
async def option_extract_place(state: AgentState) -> dict[str, Any]:
    """option.extract_place 节点。

    出参约定：
    - expected_action="place" + place_params: {orderList}
    - trace: 单条 TraceEntry，记录订单数 + orderType 分布
    """
    try:
        parsed = parse_place_params_with_lineage(
            state.get("raw_text"),
            state.get("quote_content"),
            state.get("history_messages") or [],
        )
    except (OrderScopeError, TenorError) as exc:
        return {"reply_text": str(exc), "trace": [TraceEntry(
            node="option_extract_place", decision="order_scope_unresolved",
        )]}
    validated = OptionPlaceParams.model_validate({"orderList": parsed.orders})
    order_list = [item.model_dump() for item in validated.order_list]

    prepared_state, order_list, records = prepare_order_provenance(
        state, parsed, order_list, scope="option/place",
    )
    types = [item.order_type for item in validated.order_list if item.order_type]
    decision = f"deterministic,action=place,orders={len(order_list)},types={types}"
    backend = await call_option_backend(
        prepared_state,
        intent="place_order_from_quote",
        order_list=order_list,
    )

    return {
        "field_records": records,
        "expected_action": "place",
        "place_params": validated_place_params(orderList=order_list),
        **backend,
        "trace": [TraceEntry(node="option_extract_place", decision=decision)],
    }


__all__ = ["option_extract_place"]
