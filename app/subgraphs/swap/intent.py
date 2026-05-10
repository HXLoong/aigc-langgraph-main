"""swap.intent 节点 · 互换二级意图分类。

输入：raw_text / quote_content / history_messages
输出：state['intent'] = SwapIntentType 之一（7 值）

LLM：standard 模型 + with_structured_output（ADR 0010 强制规则）。
prompt：app/prompts/swap/intent.md（Dify 原文，重构期内只读）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt
from app.subgraphs.swap.models import SwapIntentOutput


def _format_history(history: list[Message] | None) -> str:
    """把 history_messages 拼成给 LLM 看的字符串。

    格式（与 Dify 原工作流约定一致）：
        user: <内容>
        assistant: <内容>
        ...
    """
    if not history:
        return ""
    lines: list[str] = []
    for msg in history:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_user_message(state: AgentState) -> str:
    """组装 user message（含 4 个 Dify 输入变量）。"""
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    history_str = _format_history(state.get("history_messages"))
    # bot_name_list 由 ingest 节点未来从 Dify inputs 解析；M2 骨架阶段先空
    bot_name_list: list[str] = []

    return (
        f"raw_content: {raw_content}\n"
        f"quote_content: {quote_content}\n"
        f"history_query_str: {history_str}\n"
        f"bot_name_list: {bot_name_list}"
    )


@safe_node
async def swap_intent(state: AgentState) -> dict[str, Any]:
    """swap.intent 节点。

    出参约定：
    - intent: SwapIntentType 之一（小写下划线）
    - trace: 单条 TraceEntry，记录 LLM 输出
    """
    prompt = load_prompt("swap", "intent")
    llm = get_qwen_structured().with_structured_output(SwapIntentOutput)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    return {
        "intent": result.type,
        "trace": [
            TraceEntry(
                node="swap_intent",
                decision=f"intent={result.type}",
                llm_output={"type": result.type},
            )
        ],
    }


__all__ = ["swap_intent"]
