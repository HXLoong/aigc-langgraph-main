"""option.extract_confirm_cancel 节点 · 期权确认撤单订单号提取（确定性，已去 LLM 化）。

Dify DSL v2 迁移新增节点（对应 `期权-节点-确认撤单`，node_id=17793301782150），
从原 `extract_confirm`（confirm_order + confirm_cancel_order + confirm_modify_order
三合一）拆出，仅处理 confirm_cancel_order。原 LLM 调用的唯一任务是提取 Q- 订单号，
改为 app/subgraphs/option/order_id.py 确定性提取（瘦身 P1）。行为约定 1:1 对照原
提示词：仅从 quote_content（机器人撤单确认消息）提取；多单场景全部保留；
均无 → orderId: null。

输入：raw_text + quote_content
输出：state['confirm'] = {action: "cancel", orderList} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.memory import memory_order_ids
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.order_id import extract_for_confirm_cancel


@safe_node
async def option_extract_confirm_cancel(state: AgentState) -> dict[str, Any]:
    """option.extract_confirm_cancel 节点（confirm_cancel_order，确定性提取）。"""
    order_ids = extract_for_confirm_cancel(
        raw=state.get("raw_text"), quote=state.get("quote_content")
    )
    if order_ids == [None]:
        order_ids = list(memory_order_ids(state, "option")) or order_ids  # 裸确认撤单 → 记忆（ADR 0024 D4）
    order_list = [{"orderId": order_id} for order_id in order_ids]
    order_count = sum(1 for item in order_list if item["orderId"])

    backend = await call_option_backend(
        state,
        intent="confirm_cancel_order",
        order_list=order_list,
    )

    return {
        "expected_action": "cancel",
        "confirm": validated_confirm(action="cancel", orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_confirm_cancel",
                decision=f"deterministic,action=cancel,orders={order_count}",
            )
        ],
    }


__all__ = ["option_extract_confirm_cancel"]
