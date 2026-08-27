"""option.intent 节点 · 期权基础意图分类（不含平仓）。

Dify DSL v2 迁移（分支 feature/dify-dsl-migration，P2 option 域）：意图枚举收窄为
7 个基础意图 + unknown_intent（不再含 request_modify_order / confirm_modify_order
——期权无独立改单流程，改参数统一归 place_order_from_quote）。

输入：raw_text / quote_content / history_messages
输出：state['intent'] = OptionIntentType 之一（8 值）

LLM：get_qwen_structured 工厂 + with_structured_output（工厂语义现状见 ADR 0020 §4）。
prompt：`app/prompts/option/intent.md`（Dify DSL v2 同步版，node_id=1755073106378）。
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
    """组装 user message（4 个既有 Dify 输入变量 + shortname_list）。

    `shortname_list`（交易对手简称候选列表，Dify DSL v2 源
    `1772773805306.optionListStr`）取自 pre_route 解析的
    state["option_counterparties"]（后端预查对手精简列表）。
    `bot_name_list` 取 state["bot_name"]（DSL v2 start 入参）。
    """
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    history_str = _format_history(state.get("history_messages"))
    bot_name = state.get("bot_name")
    bot_name_list: list[str] = [bot_name] if bot_name else []
    shortname_list: list[str] = [
        cp.get("shortName")
        for cp in (state.get("option_counterparties") or [])
        if cp.get("shortName")
    ]

    return (
        f"raw_content: {raw_content}\n\n"
        f"quote_content: {quote_content}\n\n"
        f"history_query_str:\n{history_str}\n\n"
        f"bot_name_list: {bot_name_list}\n\n"
        f"shortname_list: {shortname_list}"
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
    # === 后处理规则修正 ===
    _combined = f"{raw} {quote}"
    _from_inquiry = any(kw in _combined for kw in (
        "询价详情", "如需下单", "名义本金", "期权费率", "标的代码",
        "已收到您的下单指令", "请引用本消息",
    ))
    if _from_inquiry and intent in ("new_inquiry", "unknown", ""):
        if any(kw in raw for kw in ("确认", "好的", "可以", "行", "下单")):
            intent = "confirm_order"
        elif any(kw in raw for kw in ("撤消", "取消", "不要", "算了")):
            intent = "cancel_order_request"
        elif any(kw in raw for kw in ("下单", "市价", "限价", "POV", "TWAP", "改")):
            intent = "place_order_from_quote"
        else:
            intent = "place_order_from_quote"

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
