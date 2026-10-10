"""在一轮渲染结束后把用户输入和机器人回复写入对话历史。"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message


@safe_node
async def record_history(state: AgentState) -> dict[str, Any]:
    messages: list[Message] = []
    raw_text = state.get("raw_text") or ""
    reply_text = state.get("reply_text") or ""
    if raw_text:
        messages.append(Message(role="user", content=raw_text))
    if reply_text:
        messages.append(Message(role="assistant", content=reply_text))
    return {"history_messages": messages}


__all__ = ["record_history"]
