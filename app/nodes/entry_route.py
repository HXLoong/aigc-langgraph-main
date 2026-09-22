"""会话保护之后的三类业务入口分流，不调用模型或后端。"""
from __future__ import annotations

from typing import Any, Literal

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.nodes.fast_query import is_existing_command, is_fast_query

EntryBranch = Literal["quick_inquiry", "existing_command_query", "pre_route"]


def select_entry_branch(state: AgentState) -> EntryBranch:
    """依次选择快速询价、非 @ 的存量指令、普通智能指令。"""
    if is_fast_query(state):
        return "quick_inquiry"
    if is_existing_command(state):
        return "existing_command_query"
    return "pre_route"


@safe_node
async def entry_route(state: AgentState) -> dict[str, Any]:
    """将选择写入当轮 trace，具体图边由同一纯函数决定。"""
    return {"trace": [TraceEntry(node="entry_route", decision=select_entry_branch(state))]}
