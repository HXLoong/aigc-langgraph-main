"""close.cancel_close 节点 · 平仓撤单订单号提取（确定性，已去 LLM 化）。

原 LLM 调用的唯一任务是提取 CO- 订单号，改为 app/subgraphs/close/order_id.py
确定性提取（瘦身 P1）——零幻觉、零成本、零延迟。行为约定 1:1 对照原提示词：
raw 的指定信号（单号 / 序号 / 合约编号，并集）→ 仅取指定订单；未指定 → 引用消息
全部；范围无法解析 → 回请求补充、不调用后端（不扩大撤单范围）。原提示词
app/prompts/option_close/cancel_close.md 已同批删除。

输入：raw_text + quote_content（引用消息含订单列表）
输出：state['cancel_params'] = {"cancelOrderNoList": [...]} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.extraction.identity import prepare_identity_scope
from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.order_id import (
    SCOPE_UNRESOLVED_REPLY,
    CloseScopeError,
    extract_for_close_orders,
    extract_order_ids,
)


@safe_node
async def close_cancel_close(state: AgentState) -> dict[str, Any]:
    """close.cancel_close 节点（确定性提取）。

    出参约定：
    - cancel_params: dict 含 cancelOrderNoList
    - trace: 单条 TraceEntry，记录提取的订单号数量
    """
    identity_origin = "quote"
    identity_evidence = state.get("quote_content") or ""
    try:
        order_nos = extract_for_close_orders(
            raw=state.get("raw_text"), quote=state.get("quote_content")
        )
    except CloseScopeError:
        return {
            "cancel_params": None,
            "api_result": None,
            "api_code": None,
            "reply_text": SCOPE_UNRESOLVED_REPLY,
            "trace": [
                TraceEntry(node="close_cancel_close", decision="close_scope_unresolved")
            ],
        }

    # 会话订单兜底：无引用、无单号时取最近一笔会话订单（沿用历史兜底）
    if not order_nos:
        conversation_orders = state.get("conversation_orders") or []
        if conversation_orders:
            last = conversation_orders[-1]
            last_order_id = last.get("orderId") or last.get("orderCode") or ""
            if last_order_id:
                order_nos = [last_order_id]
                identity_origin = "memory:conversation_orders"
                identity_evidence = "conversation_orders[-1].orderId" if last.get("orderId") else "conversation_orders[-1].orderCode"

    # 真后端调用（Dify 全 6 分支均汇入 期权平仓-参数聚合 → 期权平仓[code]，
    # cancel_close 此前遗漏了这一跳——P0 payload 对齐项，见 close/backend.py）
    prepared_state, protected_ids, records = prepare_identity_scope(
        state, order_nos, scope="close/cancel", field="cancelOrderNoList", origin=identity_origin, evidence=identity_evidence,
        explicit_raw_ids=extract_order_ids(state.get("raw_text")), selection=True,
    )
    order_nos = [order_id for order_id in protected_ids if order_id is not None]
    req_vo = build_close_order_req_vo(cancel_order_no_list=order_nos)
    backend = await call_close_backend(
        prepared_state,
        intent="close_order_cancel_request",
        close_order_req_vo=req_vo,
    )

    return {
        "field_records": records,
        "expected_action": "cancel",
        "cancel_params": validated_cancel_params(cancelOrderNoList=order_nos),
        **backend,
        "trace": [
            TraceEntry(
                node="close_cancel_close",
                decision=f"deterministic,orders={len(order_nos)}",
            )
        ],
    }


__all__ = ["close_cancel_close"]
