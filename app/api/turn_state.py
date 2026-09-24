"""一轮输入 → AgentState 的**唯一**入口（ADR 0024 D2）。

生产（app/api/routes.py）与 eval（scripts/langfuse/langfuse_eval.py）都走本函数；此前 eval 走旧兼容层
make_initial_state，它硬清空业务对象、写 AgentState 里不存在的键，评估结论与生产行为系统性偏差。
"""
from __future__ import annotations

from typing import Any

from app.graph.state import AgentState

# Dify inputs 字段名（Java 透传）→ AgentState 字段名 映射
INPUT_FIELD_ALIASES = {
    "raw_text": ("rawContent", "raw_content", "raw_text"),
    "message_id": ("messageId", "message_id"),
    "user_id": ("userId", "user_id"),
    "room_id": ("roomId", "room_id"),
    "guid": ("guid",),
    "message_content": ("messageContent", "message_content"),
    "quote_content": ("quoteContent", "quote_content"),
    "quote_appinfo": ("quoteAppinfo", "quote_appinfo"),
    "fast_query": ("fast_query", "fastQuery"),
    "at_bot": ("at_bot", "atBot"),
    "existing_command": ("existing_command", "existingCommand"),
    "bot_name": ("bot_name", "botName"),
    "operator_user_id": ("operator_user_id", "operatorUserId"),
    "retry_origin": ("retry_origin", "retryOrigin"),
    "retry_attempt": ("retry_attempt", "retryAttempt"),
    "option_counterparties_raw": ("option_counterparties", "optionCounterparties"),
    "swap_counterparties_raw": ("swap_counterparties", "swapCounterparties"),
    "input_files": ("files", "sysFiles"),
}


def inputs_to_state(inputs: dict[str, Any]) -> AgentState:
    """把 Dify inputs 转成 AgentState（接受 camelCase 和 snake_case 两种）。"""
    state: dict[str, Any] = {}
    for target, aliases in INPUT_FIELD_ALIASES.items():
        provided = [(alias, inputs[alias]) for alias in aliases if alias in inputs]
        if not provided:
            continue

        first_alias, first_value = provided[0]
        conflicting_aliases = [
            alias for alias, value in provided[1:] if value != first_value
        ]
        if conflicting_aliases:
            alias_names = ", ".join([first_alias, *conflicting_aliases])
            raise ValueError(f"输入字段 {target} 的别名值冲突: {alias_names}")

        state[target] = first_value

    if "raw_text" not in state and "message_content" in state:
        state["raw_text"] = state["message_content"]
    # checkpoint 会合并输入：所有当轮字段必须覆盖，尤其不能借用上轮消息身份。
    # 会话 ID 在路由层解析，ConversationMemory 不在此重置。
    for key in INPUT_FIELD_ALIASES:
        default: Any = None
        if key in {"raw_text", "message_content", "room_id", "user_id"}:
            default = ""
        elif key == "input_files":
            default = []
        state.setdefault(key, default)
    return state  # type: ignore[return-value]




__all__ = ["INPUT_FIELD_ALIASES", "inputs_to_state"]
