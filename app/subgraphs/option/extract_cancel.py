"""option.extract_cancel 节点 · 期权撤单订单号提取（请求撤单，确定性，已去 LLM 化）。

Dify DSL v2 迁移（对应 `期权-节点-撤单请求`，node_id=17793301778710）：仅处理
request_cancel_order（针对已正式送出订单的撤单请求）。原 LLM 调用的唯一任务是
提取 Q- 订单号，改为 app/subgraphs/option/order_id.py 确定性提取（瘦身 P1）——
零幻觉、零成本、零延迟。行为约定 1:1 对照原提示词：raw 指定具体订单则用 raw；
"全部撤单"未指定时从 quote 取全部；均无 → orderId: null。

输入：raw_text + quote_content
输出：state['expected_action'] = "cancel" + state['cancel_params'] = {orderList} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.option.backend import call_option_backend
from app.subgraphs.option.order_id import extract_for_request_cancel


@safe_node
async def option_extract_cancel(state: AgentState) -> dict[str, Any]:
    """option.extract_cancel 节点（request_cancel_order，确定性提取）。"""
    order_ids = extract_for_request_cancel(
        raw=state.get("raw_text"), quote=state.get("quote_content")
    )
    order_list = [{"orderId": order_id} for order_id in order_ids]
    order_count = sum(1 for item in order_list if item["orderId"])

    backend = await call_option_backend(
        state,
        intent="request_cancel_order",
        order_list=order_list,
    )

    return {
        "expected_action": "cancel",
        "cancel_params": validated_cancel_params(orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="option_extract_cancel",
                decision=f"deterministic,action=request_cancel,orders={order_count}",
            )
        ],
    }


__all__ = ["option_extract_cancel"]
