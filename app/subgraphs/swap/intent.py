"""swap.intent 节点 · 互换二级意图分类。

输入：raw_text / quote_content / history_messages / conversation_id
输出：state['intent'] = SwapIntentType 之一（7 值）

LLM：standard 模型 + with_structured_output（ADR 0010 强制规则）。
prompt：app/prompts/swap/intent.md（Dify 原文，重构期内只读）。

ADR 0003 灰度：通过 `resolve_prompt_version("swap", "intent", conversation_id)`
按 `app/prompts/_versions.yaml` 配置或 `OTC_PROMPT_SWAP_INTENT_VERSION` 环境变量
切到 intent_v2.md 等版本（同一会话稳定路由）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt, resolve_prompt_version
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
    - trace: 单条 TraceEntry，记录 LLM 输出 + 实际加载的 prompt name（含灰度版本号）
    """
    conversation_id = state.get("conversation_id")
    prompt_name = resolve_prompt_version("swap", "intent", conversation_id)
    prompt = load_prompt("swap", prompt_name)
    llm = get_qwen_thinking().with_structured_output(SwapIntentOutput)

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
                decision=f"intent={result.type} prompt={prompt_name}",
                llm_output={"type": result.type, "prompt_name": prompt_name},
            )
        ],
    }


__all__ = ["swap_intent"]
