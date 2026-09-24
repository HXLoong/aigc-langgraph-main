"""persist 节点：把本轮 trace 沉淀到持久化层。

- LangFuse：通过 CallbackHandler 自动写（本节点不重复写）
- MySQL `langgraph_node_trace`：经 app/storage/node_trace.py 每条 trace 写一行

写 MySQL 失败**不阻塞业务主流程**：记录告警后返回；LangFuse 与 MySQL 互相独立。
"""
from __future__ import annotations

import logging
from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState
from app.storage.node_trace import write_node_trace

logger = logging.getLogger(__name__)


@safe_node
async def persist(state: AgentState) -> dict[str, Any]:
    """把 state['trace'] 写到 MySQL `langgraph_node_trace` 表。

    幂等：基于 (message_id, step_index) 行内顺序——同一 message 重复写不会冲突，
    但会插入新一组（业务侧按 created_at 取最新）。
    """
    trace = state.get("trace") or []
    if not trace:
        logger.debug("persist: empty trace, skip")
        return {}

    message_id = str(state.get("message_id") or "")
    thread_id = state.get("conversation_id") or ""
    trace_id = state.get("trace_id") or ""
    logger.info(
        "persist trace_count=%d conversation_id=%s product_type=%s intent=%s",
        len(trace),
        thread_id,
        state.get("product_type"),
        state.get("intent"),
    )
    try:
        await write_node_trace(trace, message_id, thread_id, trace_id)
    except Exception as exc:  # noqa: BLE001 - 监控不能影响业务
        logger.warning("persist: MySQL 写入失败（不影响主流程）: %s", exc)
    return {}


__all__ = ["persist"]
