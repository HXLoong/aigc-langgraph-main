"""close.query_status 节点 · 平仓订单状态查询参数提取。

输入：raw_text（用户提到的订单号列表）
输出：state['query_filter'] = {queryOrderNoList: [...]}

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/query_status.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_query_filter
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.models import QueryStatusParams
from app.subgraphs.option.backend import call_option_backend


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    return f"用户输入内容：{raw_content}"


@safe_node
async def close_query_status(state: AgentState) -> dict[str, Any]:
    """close.query_status 节点。"""
    prompt = load_prompt("option_close", "query_status")
    llm = get_qwen_thinking().with_structured_output(QueryStatusParams)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    order_list = [{"orderId": oid} for oid in result.queryOrderNoList]
    backend = await call_option_backend(
        state,
        intent="close_order_order_query",
        order_list=order_list,
    )

    return {
        "query_filter": validated_query_filter(queryOrderNoList=result.queryOrderNoList),
        **backend,
        "trace": [
            TraceEntry(
                node="close_query_status",
                decision=f"orders={len(result.queryOrderNoList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_query_status"]
