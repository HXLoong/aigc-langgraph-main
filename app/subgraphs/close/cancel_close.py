"""close.cancel_close 节点 · 平仓撤单订单号提取。

输入：raw_text + quote_content（引用消息含订单列表）
输出：state['cancel_params'] = {"cancelOrderNoList": [...]}

LLM：standard 模型 + with_structured_output（ADR 0010 强制规则）。
prompt：app/prompts/option_close/cancel_close.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt
from app.subgraphs.close.models import CancelCloseParams


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    return (
        f"用户发送消息：{raw_content}\n"
        f"用户引用消息：{quote_content}"
    )


@safe_node
async def close_cancel_close(state: AgentState) -> dict[str, Any]:
    """close.cancel_close 节点。

    出参约定：
    - cancel_params: dict 含 cancelOrderNoList
    - trace: 单条 TraceEntry，记录提取的订单号数量
    """
    prompt = load_prompt("option_close", "cancel_close")
    llm = get_qwen_structured().with_structured_output(CancelCloseParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    return {
        "cancel_params": {
            "cancelOrderNoList": result.cancelOrderNoList,
        },
        "trace": [
            TraceEntry(
                node="close_cancel_close",
                decision=f"orders={len(result.cancelOrderNoList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_cancel_close"]
