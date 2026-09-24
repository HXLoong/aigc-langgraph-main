"""平仓最终确认：明确口令、当前引用与唯一订单范围由共享代码协议校验。"""
from __future__ import annotations

from typing import Any

from app.domain.confirmation import parse_confirmation
from app.extraction.identity import prepare_identity_scope
from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.order_id import extract_order_ids


@safe_node
async def close_confirm_close(state: AgentState) -> dict[str, Any]:
    """close.confirm_close 节点（确定性提取）。

    出参约定：
    - confirm: dict 含 confirmOrderNoList + action="close"（与 swap.confirm
      合并版同款 action 字段约定）
    - trace: 单条 TraceEntry，记录提取的订单号数量
    """
    identity_origin = "quote"
    identity_evidence = state.get("quote_content") or ""
    confirmation = parse_confirmation(
        state.get("raw_text"), state.get("quote_content"), product="close", action="close",
    )
    if confirmation.error:
        return {"confirm": None, "reply_text": confirmation.correction(),
                "trace": [TraceEntry(node="close_confirm_close", decision=f"confirmation:{confirmation.error}")]}
    confirm_ids = list(confirmation.order_ids)

    prepared_state, protected_ids, records = prepare_identity_scope(
        state, confirm_ids, scope="close/confirm", field="confirmOrderNoList", origin=identity_origin, evidence=identity_evidence,
        explicit_raw_ids=extract_order_ids(state.get("raw_text")), selection=True,
    )
    confirm_ids = [order_id for order_id in protected_ids if order_id is not None]
    confirmation.verify_scope(confirm_ids)
    req_vo = build_close_order_req_vo(confirm_order_no_list=confirm_ids)
    backend = await call_close_backend(
        prepared_state,
        intent="close_order_confirm",
        close_order_req_vo=req_vo,
    )

    return {
        "field_records": records,
        "expected_action": "close",
        "confirm": validated_confirm(action="close", confirmOrderNoList=confirm_ids),
        **backend,
        "trace": [
            TraceEntry(
                node="close_confirm_close",
                decision=f"deterministic,orders={len(confirm_ids)}",
            )
        ],
    }


__all__ = ["close_confirm_close"]
