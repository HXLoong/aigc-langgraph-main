"""会话保护后的 Dify 兼容入口：存量优先，再按机器人版本分流。"""
from __future__ import annotations

from typing import Any, Literal

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.nodes.fast_query import is_existing_command, is_fast_query

EntryBranch = Literal["quick_inquiry", "existing_command_query", "pre_route", "ignore"]


def select_entry_branch(state: AgentState) -> EntryBranch:
    """非 @ 存量指令绕过版本；未配置版本按 V1，非法版本静默。"""
    if is_existing_command(state):
        return "existing_command_query"
    supplied_version = state.get("robot_version")
    version = "V1" if supplied_version is None or supplied_version == "" else supplied_version
    if version not in ("V1", "V2"):
        return "ignore"
    if is_fast_query(state):
        return "existing_command_query" if version == "V1" else "quick_inquiry"
    return "pre_route" if version == "V2" else "ignore"


@safe_node
async def entry_route(state: AgentState) -> dict[str, Any]:
    """将选择写入当轮 trace，具体图边由同一纯函数决定。"""
    branch = select_entry_branch(state)
    version = state.get("robot_version")
    invalid_version = version is not None and version != "" and version not in ("V1", "V2")
    decision = "ignore:invalid_robot_version" if branch == "ignore" and invalid_version else branch
    result: dict[str, Any] = {"entry_branch": branch,
                             "trace": [TraceEntry(node="entry_route", decision=decision)]}
    # 快速入口已明确产品与动作，标签由规则给出，不额外请求普通解析模型。
    if branch in {"quick_inquiry", "existing_command_query"}:
        result.update(product_type="option", intent="new_inquiry")
    elif branch == "ignore":
        result.update(product_type="unknown", intent="", reply_text="IGNORE_REQUEST_NOT_REPLY_USER")
    return result
