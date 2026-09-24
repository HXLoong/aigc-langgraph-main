"""option 子图的 PromptSpec 共享积木（ADR 0023）。

1 个 LLM extract 节点（询价 extract_inquiry）的 user 消息模板；
4 个订单号节点 + 2 个下单/确认下单节点（2026-09 去 LLM 化）不再使用，
此前每个节点各自复制一份 _format_history + _build_user_message；现在只在这里定义一次。
"""
from __future__ import annotations

from app.graph.state import AgentState
from app.prompts import blocks

EXTRACT_INPUTS: tuple[str, ...] = ("raw_text", "quote_content", "history_messages")


INTENT_INPUTS: tuple[str, ...] = (
    "raw_text", "quote_content", "history_messages", "option_counterparties",
)


def intent_user(state: AgentState) -> str:
    return blocks.source_payload(state, context={
        "shortname_list": blocks.shortnames(state.get("option_counterparties")),
    })
