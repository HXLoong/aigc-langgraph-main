"""根据确定性产品和引用准备只读上下文，所有查询都发生在模型请求之前。"""
from __future__ import annotations

import json
from typing import Any

from app.domain.order_ids import CONTRACT_CODE_RE
from app.graph.retry import io_node
from app.graph.state import AgentState, TraceEntry
from app.parsing.close_reference import needs_close_order_context, parse_reference_message
from app.tools.exceptions import EmptyBackendResultError
from app.tools.option_client import OptionClientHttpx


@io_node
async def prepare_parse_context(state: AgentState) -> dict[str, Any]:
    """平仓金额语义需要上下文时按明确身份读取，不先调用模型分类。"""
    if state.get("error") or state.get("reply_text") or state.get("product_type") != "option_close":
        return {}
    raw, quote = state.get("raw_text") or "", state.get("quote_content") or ""
    reference = parse_reference_message(quote, raw)
    context: dict[str, Any] = {"reference": reference, "orders": [], "sources": {}}
    # 1. 当前动作先决定是否需要读取；引用里有身份不能扩大到持仓、撤单或查询。
    contracts = list(dict.fromkeys(reference["contractCodes"] + CONTRACT_CODE_RE.findall(quote)))
    if not needs_close_order_context(raw, quote) or not (reference["orderIds"] or contracts):
        return {"parse_context": context,
                "trace": [TraceEntry(node="prepare_parse_context", decision="skipped:not_close_request_or_no_target")]}

    # 2. 保留后端原始上下文，不在本地计算比例、余额或补齐订单参数。
    response = await OptionClientHttpx().query_close_orders(
        order_ids=reference["orderIds"], contract_codes=contracts,
        room_id=state.get("room_id"), message_id=state.get("message_id"),
    )
    rows = response.get("data")
    if response.get("code") != 0 or not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise EmptyBackendResultError("option", response.get("code"))
    context["orders"] = rows
    context["sources"] = {f"context:order:{index}": json.dumps(row, ensure_ascii=False)
                          for index, row in enumerate(rows)}
    return {"parse_context": context,
            "trace": [TraceEntry(node="prepare_parse_context", decision=f"orders={len(rows)}")]}
