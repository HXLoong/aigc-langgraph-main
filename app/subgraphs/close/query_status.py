"""close.query_status 节点 · 平仓订单状态查询参数提取。

输入：raw_text（用户提到的订单号列表）
输出：state['query_filter'] = {queryOrderNoList: [...]}

LLM：standard 模型 + with_structured_output（ADR 0010）。
prompt：app/prompts/option_close/query_status.md。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.models import QueryStatusParams


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

    return {
        "query_filter": {
            "queryOrderNoList": result.queryOrderNoList,
        },
        "trace": [
            TraceEntry(
                node="close_query_status",
                decision=f"orders={len(result.queryOrderNoList)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["close_query_status"]
