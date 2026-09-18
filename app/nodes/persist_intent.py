"""回复前等待 Java 消息记录写回，失败由 safe_node 留下 trace。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.graph.safe_node import NodeFn, safe_node
from app.graph.state import AgentState, TraceEntry
from app.tools.message_client import MessageClient, SetIntentRequest


def make_persist_intent(
    message_client_factory: Callable[[], MessageClient] | None,
) -> NodeFn[[AgentState]]:
    """未注入客户端时跳过消息写回，供单测及直接运行的 harness 使用。"""

    @safe_node
    async def persist_intent(state: AgentState) -> dict[str, Any]:
        if message_client_factory is None:
            return {"trace": [TraceEntry(node="persist_intent", decision="skipped")]}

        req = SetIntentRequest(
            conversation_id=state["conversation_id"],
            message_id=str(state["message_id"]),
            intent=state.get("intent") or "unknown_intent",
            product_type=1 if state.get("product_type") == "swap" else 0,
        )
        await message_client_factory().set_intent(req)
        return {}

    return persist_intent
