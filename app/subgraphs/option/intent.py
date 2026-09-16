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
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts.spec import PromptSpec, register
from app.subgraphs.option.models import OptionIntentOutput
from app.subgraphs.option.prompting import INTENT_INPUTS, intent_user

SPEC = register(PromptSpec(
    category="option",
    name="intent",
    output_model=OptionIntentOutput,
    inputs=INTENT_INPUTS,
    user_builder=intent_user,
))

#: 兼容旧测试 / 调用点：user 消息拼装已收敛到 app/subgraphs/option/prompting.intent_user
_build_user_message = intent_user


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

    messages, _prompt_name = SPEC.build_messages(state)
    llm = get_qwen_structured().with_structured_output(OptionIntentOutput)
    result: Any = await llm.ainvoke(messages)

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
