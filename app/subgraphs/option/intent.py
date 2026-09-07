"""option.intent 节点 · 期权基础意图分类（不含平仓）。

ADR 0011 二次修订：从原"意图识别+参数提取"巨型 prompt 拆出独立分类节点。
当前节点仅做意图分类（10 个基础意图），参数提取由 5 个 extract 节点处理。

输入：raw_text / quote_content / history_messages
输出：state['intent'] = OptionIntentType 之一（10 值）

LLM：get_qwen_structured 工厂 + with_structured_output（工厂语义现状见 ADR 0020 §4）。
prompt：`app/prompts/option/intent.md`（拆分后的轻量版，~80 行）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt
from app.subgraphs.option.models import OptionIntentOutput


def _format_history(history: list[Message] | None) -> str:
    """与 swap.intent 同款历史拼接（user/assistant 行）。"""
    if not history:
        return ""
    lines: list[str] = []
    for msg in history:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_user_message(state: AgentState) -> str:
    """组装 user message（4 个 Dify 输入变量）。"""
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    history_str = _format_history(state.get("history_messages"))
    bot_name_list: list[str] = []

    return (
        f"raw_content: {raw_content}\n\n"
        f"quote_content: {quote_content}\n\n"
        f"history_query_str:\n{history_str}\n\n"
        f"bot_name_list: {bot_name_list}"
    )


@safe_node
async def option_intent(state: AgentState) -> dict[str, Any]:
    """option.intent 节点。

    出参约定：
    - intent: OptionIntentType 之一
    - trace: 单条 TraceEntry，记录 LLM 输出
    """
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""

    # === 确定性快速路径（调 LLM 前） ===
    if raw.strip() == "-":
        return {
            "intent": "confirm_order",
            "trace": [TraceEntry(node="option_intent", decision="deterministic_dash")],
        }
    if "确认下单" in raw:
        return {
            "intent": "confirm_order",
            "trace": [TraceEntry(node="option_intent", decision="deterministic_confirm")],
        }
    if "撤单" in raw and ("撤单" in quote or "撤单请求" in quote):
        return {
            "intent": "cancel_order_request",
            "trace": [TraceEntry(node="option_intent", decision="deterministic_cancel")],
        }

    prompt = load_prompt("option", "intent")
    llm = get_qwen_structured().with_structured_output(OptionIntentOutput)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    intent = result.type
    return {
        "intent": intent,
        "trace": [
            TraceEntry(
                node="option_intent",
                decision=f"intent={intent}",
                llm_output={"type": intent},
            )
        ],
    }


__all__ = ["option_intent"]
