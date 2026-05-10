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
    """M1 占位：不修改 state；由 API 层从 final state 直接构造 Dify outputs。

    M2 阶段：在此处加业务回复 LLM 生成。
    """
    return {}
