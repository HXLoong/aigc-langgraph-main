"""ingest 节点：从 Dify Workflow Run inputs 进入主图的薄入口。

M1 阶段：解析必填字段 + 设默认 product_type。
M2 阶段：增强为基于 raw_text + history 的 LLM 一级路由器（intent_route）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState


@safe_node
async def ingest(state: AgentState) -> dict[str, Any]:
    """入口节点：M1 占位实现。

    上游已由 `app/api/routes.py` 把 Dify inputs 解构成 9 个机器人上下文字段
    （contracts §2.1 §3.1）放进 state，本节点只做最低校验 + 默认值。

    M2 阶段：在此处加 LLM 一级路由（基于 raw_text 决定 product_type）。
    """
    update: dict[str, Any] = {}

    # 默认 product_type = swap（M1 占位；M2 用 LLM 路由替换）
    if not state.get("product_type"):
        update["product_type"] = "swap"

    return update
