"""close.confirm_close 节点 · 确认平仓订单号提取（确定性，已去 LLM 化）。

原 LLM 调用的唯一任务是提取 CO- 订单号，改为 app/subgraphs/close/order_id.py
确定性提取（瘦身 P1）。行为约定 1:1 对照原提示词：raw 的指定信号（单号 / 序号 /
合约编号，并集）→ 仅取指定订单；未指定 → 引用消息全部；范围无法解析 → 回请求
补充、不调用后端。原提示词 app/prompts/option_close/confirm_close.md 已同批删除。

输入：raw_text + quote_content（引用消息含订单列表）
输出：state['confirm'] = {"confirmOrderNoList": [...], "action": "close"} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
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
async def close_confirm_close(state: AgentState) -> dict[str, Any]:
    """close.confirm_close 节点（确定性提取）。

    出参约定：
    - confirm: dict 含 confirmOrderNoList + action="close"（与 swap.confirm
      合并版同款 action 字段约定）
    - trace: 单条 TraceEntry，记录提取的订单号数量
    """
    try:
        confirm_ids = extract_for_close_orders(
            raw=state.get("raw_text"), quote=state.get("quote_content")
        )
    except CloseScopeError:
        return {
            "confirm": None,
            "api_result": None,
            "api_code": None,
            "reply_text": SCOPE_UNRESOLVED_REPLY,
            "trace": [
                TraceEntry(node="close_confirm_close", decision="close_scope_unresolved")
            ],
        }

    # 真后端调用：confirmOrderNoList 进 closeOrderReqVO（不是 option 域的 orderList）
    req_vo = build_close_order_req_vo(confirm_order_no_list=confirm_ids)
    backend = await call_close_backend(
        state,
        intent="close_order_confirm",
        close_order_req_vo=req_vo,
    )

    return {
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
