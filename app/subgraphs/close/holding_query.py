"""持仓查询：仅装配本次明确给出的过滤条件，由父图清洗后读取 Java 回执。"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_close_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.parsing.evidence import verify_instruction
from app.parsing.models import CloseInstruction
from app.subgraphs.close.backend import prepare_close_request


@safe_node
async def close_holding_query(state: AgentState) -> dict[str, Any]:
    """只准备持仓查询参数；父图的只读 HTTP 节点独立重试。"""
    parsed = CloseInstruction.model_validate(state.get("parsed_instruction") or {})
    if parsed.intent != "close_order_query":
        raise ValueError("持仓查询节点收到其它业务动作")
    records = verify_instruction(parsed, state)
    # 字段名映射属于传输契约，未提供的过滤条件由后端决定。
    filters = parsed.query.model_dump(exclude_none=True, exclude_unset=True) if parsed.query else {}
    wire = dict(filters)
    if "closeable_only" in wire:
        wire["allowCloseOut"] = wire.pop("closeable_only")
    request_update = await prepare_close_request(state, intent=parsed.intent, close_order_req_vo={"contractQuery": wire})
    return {"close_params": validated_close_params(**filters), "field_records": records, **request_update,
            "trace": [TraceEntry(node="close_holding_query", decision=f"filters={len(wire)}")]}
