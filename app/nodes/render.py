"""render 节点：从 final state 渲染回复给 API 层。

M1 阶段：占位（API 层直接从 final state 构造 Dify Workflow Run API outputs）。
M2 阶段：在此处接入业务回复 LLM 生成（按 intent + 业务对象生成自然语言回复）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState


@safe_node
async def render(state: AgentState) -> dict[str, Any]:
    """透传 reply_text（子图已生成）或 api_result（后端返回）。"""
    reply = state.get("reply_text") or state.get("api_result") or ""
    if reply:
        return {"reply_text": reply}
    if state.get("error"):
        return {"reply_text": f"处理失败：{state['error']}"}
    if state.get("product_type") == "unknown":
        return {"reply_text": "未识别到有效指令，请明确指定产品（期权/互换）和操作（询价/下单/撤单等）。"}
    return {}
