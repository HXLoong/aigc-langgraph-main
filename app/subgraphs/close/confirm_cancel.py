"""close.confirm_cancel 节点 · 确认撤销平仓订单号提取。

输入：raw_text + quote_content（引用消息含订单列表）
输出：state['confirm'] = {action: "cancel_close", confirmCancelOrderNoList: [...]}

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/confirm_cancel.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_confirm
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.aggregate import build_close_order_req_vo
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import ConfirmCancelParams


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return (
        f"用户发送消息：{raw_content}\n"
        f"用户引用消息：{quote_content}"
    )


@safe_node
async def close_confirm_cancel(state: AgentState) -> dict[str, Any]:
    """close.confirm_cancel 节点。"""
    prompt = load_prompt("option_close", "confirm_cancel")
    llm = get_qwen_thinking().with_structured_output(ConfirmCancelParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    req_vo = build_close_order_req_vo(
        confirm_cancel_order_no_list=result.confirm_cancel_order_no_list
    )
    backend = await call_close_backend(
        state,
        intent="close_order_cancel_confirm",
        close_order_req_vo=req_vo,
    )

    return {
        "confirm": validated_confirm(action="cancel_close", confirmCancelOrderNoList=result.confirm_cancel_order_no_list),
        **backend,
        "trace": [
            TraceEntry(
                node="close_confirm_cancel",
                decision=f"orders={len(result.confirm_cancel_order_no_list)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_confirm_cancel"]
