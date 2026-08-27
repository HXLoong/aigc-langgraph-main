"""swap.cancel 节点 · 互换撤单订单号提取。

输入：raw_text + quote_content
输出：state['cancel_params'] = {orderList}

注：ADR 0001 D6 列了 swap.cancel + swap.cancel_extract 两个节点。骨架阶段
合并为单节点 swap.cancel —— swap.intent 已做意图分类，不需要额外的"路由层"
cancel.py。如果未来出现需要拆分的业务（如双阶段确认），再单独 PR 扩展。

LLM：thinking 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/swap/cancel_order.md（DSL v2 互换-节点-撤单，2 变量：
raw_content / quote_content，不再含 history_query_str）。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_cancel_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.swap.backend import call_swap_backend
from app.subgraphs.swap.models import SwapCancelParams


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return f"raw_content：{raw_content}\nquote_content：{quote_content}"


@safe_node
async def swap_cancel(state: AgentState) -> dict[str, Any]:
    """swap.cancel 节点。"""
    prompt = load_prompt("swap", "cancel_order")
    llm = get_qwen_thinking().with_structured_output(SwapCancelParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    order_list = [item.model_dump() for item in result.orderList]
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
                decision=f"orders={len(result.orderList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_cancel"]
