"""swap.cancel 节点 · 互换撤单订单号提取(确定性,已去 LLM 化)。

瘦身 P1(docs/swap-prompt-slimming-assessment.md 病灶 2):原 LLM 调用的唯一
任务是提取 H- 订单号,改为 app/subgraphs/swap/order_id.py 确定性提取——
零幻觉、零成本、零延迟。原提示词 app/prompts/swap/cancel_order.md 保留为
非活跃资产。行为约定 1:1 对照原提示词:raw 明确指定优先,否则 quote 全部。

输入:raw_text + quote_content
输出:state['cancel_params'] = {orderList} + 后端调用结果
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.order_id import extract_for_cancel


@safe_node
async def swap_cancel(state: AgentState) -> dict[str, Any]:
    """swap.cancel 节点(确定性提取)。"""
    order_ids = extract_for_cancel(
        raw=state.get("raw_text"), quote=state.get("quote_content")
    )
    order_list = [{"orderId": oid} for oid in order_ids]

    backend = await call_swap_backend(
        state,
        intent="cancel_order_request",
        order_list=order_list,
    )

    return {
        "cancel_params": validated_cancel_params(orderList=order_list),
        **backend,
        "trace": [
            TraceEntry(
                node="swap_cancel",
                decision=f"deterministic,orders={len(order_list)}",
            )
        ],
    }


__all__ = ["swap_cancel"]
