"""close.intent 节点 · 期权平仓意图分类（6 个 close_order_* + unknown）。

工程适配：Dify 原 `option_close/intent.md` 的输出契约是"仅输出意图 code 字符串"
（如 `close_order_query`），与 `with_structured_output` 不兼容。

策略：保留 Dify 原 prompt 不动（ADR 0003 只读约定），节点层在 system 末尾
追加 JSON 输出指令，让 standard 模型 + structured output 能正常工作。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, Message, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import load_prompt
from app.subgraphs.close.models import CloseIntentOutput

#: 后置追加到 prompt.system 末尾的 JSON 输出指令（不修改 Dify 原 .md）
_JSON_OUTPUT_INSTRUCTION = """

## 工程层输出格式约束（不修改 Dify 原文逻辑）

请严格输出 JSON 对象，仅含一个 type 字段，绝不输出其他文字：

{"type": "<6 个 close_order_* 之一 或 unknown_intent>"}
"""


def _format_history(history: list[Message] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for msg in history:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    history_str = _format_history(state.get("history_messages"))
    return (
        f"raw_content: {raw_content}\n\n"
        f"quote_content: {quote_content}\n\n"
        f"history_query_str:\n{history_str}"
    )


@safe_node
async def close_intent(state: AgentState) -> dict[str, Any]:
    """close.intent 节点。"""
    prompt = load_prompt("option_close", "intent")
    augmented_system = prompt.system + _JSON_OUTPUT_INSTRUCTION

    llm = get_qwen_thinking().with_structured_output(CloseIntentOutput)
    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", augmented_system),
            ("user", user_message),
        ]
    )

    intent = result.type
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content") or ""
    text = f"{raw} {quote}"

    # 规则修正：含合约编号+平仓动作词但 LLM 误分为 query → request
    if intent == "close_order_query":
        import re as _re
        has_contract = bool(_re.search(r"(?:OPT|OPTG)-\w+", text))
        close_actions = ("平掉","平仓","平剩","平留","市价平","部分平","我想平","我要平")
        if has_contract and any(a in text for a in close_actions):
            intent = "close_order_request"
    # "撤单" 关键词 → close_order_cancel_request（覆盖 LLM 误判）
    if "撤单" in raw and intent not in (
        "close_order_cancel_confirm", "close_order_cancel_request"
    ):
        intent = "close_order_cancel_request"
    # "查可平持仓"/"查询持仓" → close_order_query
    if any(kw in raw for kw in ("查可平持仓", "查询持仓", "我有哪些")):
        intent = "close_order_query"
    # "确认撤单" → close_order_cancel_confirm（修复历史 typo：曾写成不存在的
    # close_order_confirm_cancel，导致规则从未命中、静默 fall through 到 unknown）
    if "确认撤单" in raw:
        intent = "close_order_cancel_confirm"
    # "取消" + quote 中有撤单上下文 → confirm_cancel
    if "取消" in raw and ("撤单" in quote or "撤单请求" in quote):
        intent = "close_order_confirm_cancel"
    # "序号N" + 平仓动作词 → close_order_request
    import re as _re2
    if _re2.search(r"序号\s*\d", raw):
        close_kw = ("平", "留", "全平", "拉满", "跟量", "pov", "POV")
        if any(kw in raw.lower() for kw in close_kw):
            intent = "close_order_request"
    # "拉满跟量"/"全部最大" + 金额 → close_order_request
    if any(kw in raw for kw in ("拉满跟量", "全部最大", "全跟量")) and _re2.search(r"\d+\s*万", raw):
        intent = "close_order_request"

    return {
        "intent": intent,
        "trace": [
            TraceEntry(
                node="close_intent",
                decision=f"intent={intent}",
                llm_output={"type": intent},
            )
        ],
    }


__all__ = ["close_intent"]
