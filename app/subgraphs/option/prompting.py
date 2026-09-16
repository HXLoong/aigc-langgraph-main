"""option 子图的 PromptSpec 共享积木（ADR 0023）。

1 个 LLM extract 节点（询价 extract_inquiry）的 user 消息模板；
4 个订单号节点 + 2 个下单/确认下单节点（2026-09 去 LLM 化）不再使用，
此前每个节点各自复制一份 _format_history + _build_user_message；现在只在这里定义一次。
"""
from __future__ import annotations

from app.graph.state import AgentState
from app.prompts import blocks

EXTRACT_INPUTS: tuple[str, ...] = ("raw_text", "quote_content", "history_messages")


def extract_user(state: AgentState) -> str:
    return (
        f"用户消息：{state.get('raw_text', '') or ''}\n\n"
        f"引用消息：{state.get('quote_content') or ''}\n\n"
        f"历史对话：\n{blocks.format_history(state.get('history_messages'))}"
    )


INTENT_INPUTS: tuple[str, ...] = (
    "raw_text", "quote_content", "history_messages", "bot_name", "option_counterparties",
)


def intent_user(state: AgentState) -> str:
    """intent 节点的 5 个输入变量（Dify DSL v2 `期权-意图识别` user 模板）。"""
    bot_name = state.get("bot_name")
    return (
        f"raw_content: {state.get('raw_text', '') or ''}\n\n"
        f"quote_content: {state.get('quote_content') or ''}\n\n"
        f"history_query_str:\n{blocks.format_history(state.get('history_messages'))}\n\n"
        f"bot_name_list: {[bot_name] if bot_name else []}\n\n"
        f"shortname_list: {blocks.shortnames(state.get('option_counterparties'))}"
    )
