"""persist 节点：把 trace 沉淀到持久化层。

M1 阶段：log trace 到 stdout（不写 MySQL）。
M3 阶段：写 node_trace 表（ADR 0004），同时由 LangFuse callback handler 自动写 LangFuse。
"""
from __future__ import annotations

import logging
from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState

logger = logging.getLogger(__name__)


@safe_node
async def persist(state: AgentState) -> dict[str, Any]:
    """M1 占位：log trace 摘要。M3 阶段接通 node_trace MySQL 表。"""
    trace = state.get("trace", [])
    logger.info(
        "persist trace_count=%d conversation_id=%s product_type=%s intent=%s",
        len(trace),
        state.get("conversation_id"),
        state.get("product_type"),
        state.get("intent"),
    )
    return {}
