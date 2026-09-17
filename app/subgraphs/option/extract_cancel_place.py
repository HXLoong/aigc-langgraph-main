"""option.extract_cancel_place 节点 · 期权取消下单订单号提取（确定性，已去 LLM 化）。

Dify DSL v2 迁移新增节点（对应 `期权-节点-取消下单`，node_id=17793301887260），
从原 `extract_cancel`（cancel_order_request + request_cancel_order 合并版）拆出，
仅处理 cancel_order_request（订单未正式送出阶段的作废）。原 LLM 调用的唯一任务是
提取 Q- 订单号，改为 app/subgraphs/option/order_id.py 确定性提取（瘦身 P1）。
行为约定 1:1 对照原提示词：仅从 quote_content 提取（用户引用确认卡选择取消）；
均无 → orderId: null。

输入：raw_text + quote_content
输出：state['expected_action'] = "cancel" + state['cancel_params'] = {orderList} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.order_id import extract_for_cancel_place


@safe_node
async def option_extract_cancel_place(state: AgentState) -> dict[str, Any]:
    """option.extract_cancel_place 节点（cancel_order_request，确定性提取）。"""
    order_ids = extract_for_cancel_place(
        raw=state.get("raw_text"), quote=state.get("quote_content")
    )
    order_list = [{"orderId": order_id} for order_id in order_ids]
    order_count = sum(1 for item in order_list if item["orderId"])

    backend = await call_option_backend(
        state,
        intent="cancel_order_request",
        order_list=order_list,
    )

    return {
        "expected_action": "cancel",
        "cancel_params": validated_cancel_params(orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_cancel_place",
                decision=f"deterministic,action=cancel_request,orders={order_count}",
            )
        ],
    }


__all__ = ["option_extract_cancel_place"]
