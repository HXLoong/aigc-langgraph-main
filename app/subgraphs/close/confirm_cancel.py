"""close.confirm_cancel 节点 · 确认撤销平仓订单号提取（确定性，已去 LLM 化）。

原 LLM 调用的唯一任务是提取 CO- 订单号，改为 app/subgraphs/close/order_id.py
确定性提取（瘦身 P1）。行为约定 1:1 对照原提示词：有指定信号（单号 / 序号，并集）
→ 仅取子集；未指定 → 引用消息全部（@提及 / 引号包裹 / UUID 均不影响提取）；
范围无法解析 → 回请求补充、不调用后端。原提示词
app/prompts/option_close/confirm_cancel.md 已同批删除。

输入：raw_text + quote_content（引用消息含订单列表）
输出：state['confirm'] = {action: "cancel_close", confirmCancelOrderNoList: [...]} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.memory import memory_order_ids
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.order_id import (
    SCOPE_UNRESOLVED_REPLY,
    CloseScopeError,
    extract_for_close_orders,
)


@safe_node
async def close_confirm_cancel(state: AgentState) -> dict[str, Any]:
    """close.confirm_cancel 节点（确定性提取）。"""
    try:
        confirm_cancel_ids = extract_for_close_orders(
            raw=state.get("raw_text"), quote=state.get("quote_content")
        )
        if not confirm_cancel_ids:
            # 无引用、无指定信号的裸确认 → 上一轮平仓请求记下的单号（ADR 0024 D4）
            confirm_cancel_ids = memory_order_ids(state, "option_close")
    except CloseScopeError:
        return {
            "confirm": None,
            "api_result": None,
            "api_code": None,
            "reply_text": SCOPE_UNRESOLVED_REPLY,
            "trace": [
                TraceEntry(
                    node="close_confirm_cancel", decision="close_scope_unresolved"
                )
            ],
        }

    req_vo = build_close_order_req_vo(
        confirm_cancel_order_no_list=confirm_cancel_ids
    )
    backend = await call_close_backend(
        state,
        intent="close_order_cancel_confirm",
        close_order_req_vo=req_vo,
    )

    return {
        "expected_action": "cancel",
        "confirm": validated_confirm(
            action="cancel_close", confirmCancelOrderNoList=confirm_cancel_ids
        ),
        **backend,
        "trace": [
            TraceEntry(
                node="close_confirm_cancel",
                decision=f"deterministic,orders={len(confirm_cancel_ids)}",
            )
        ],
    }


__all__ = ["close_confirm_cancel"]
