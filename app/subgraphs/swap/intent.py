"""swap.intent 节点 · 互换二级意图分类。

输入：raw_text / quote_content / swap_counterparties / conversation_id
输出：state['intent'] = SwapIntentType 之一（7 值）

LLM：get_qwen_thinking 工厂 + with_structured_output（工厂语义现状见 ADR 0020 §4 / #158 裁决）。
prompt：app/prompts/swap/intent.md（DSL v2 互换-节点-意图识别，2026-08 版）。

ADR 0003 灰度：通过 `resolve_prompt_version("swap", "intent", conversation_id)`
按 `app/prompts/_versions.yaml` 配置或 `OTC_PROMPT_SWAP_INTENT_VERSION` 环境变量
切版本（同一会话稳定路由）；DSL v2 迁移后旧 g008 canary（intent_v2.md）已废弃
（新提示词已内置对应仲裁规则），当前无生产灰度条目，机制保留供未来使用。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.models import SwapIntentOutput

#: Dify code 节点 1755072896717 `has_confirmation_keyword` 同款词表；命中直接走 confirm_order。
#: 2026-09-11 回归 Dify 原文后 intent.md 枚举已不含 confirm_order（Dify 靠前置分流），
#: app 侧必须移植该分流，否则确认下单链路失效（提示词治理评估 SW-INC-01）。
CONFIRM_ORDER_KEYWORDS: tuple[str, ...] = ("确认下单", "确定下单", "确认订单", "下单确认")


def has_confirm_order_keyword(raw: str | None) -> bool:
    """raw_content 是否含「确认下单」类关键词（Dify has_confirmation_keyword 同款）。"""
    text = (raw or "").strip()
    return any(word in text for word in CONFIRM_ORDER_KEYWORDS)


def _build_user_message(state: AgentState) -> str:
    """DSL v2 互换-节点-意图识别.md 的 3 个输入变量；shortname_list 近似 Dify trsShortListStr。"""
    return (
        f"raw_content：{state.get('raw_text', '') or ''}\n"
        f"quote_content：{state.get('quote_content') or ''}\n"
        f"shortname_list：{', '.join(blocks.shortnames(state.get('swap_counterparties')))}"
    )


SPEC = register(PromptSpec(
    category="swap",
    name="intent",
    output_model=SwapIntentOutput,
    inputs=("raw_text", "quote_content", "swap_counterparties", "conversation_id"),
    user_builder=_build_user_message,
    gray=True,
))


@safe_node
async def swap_intent(state: AgentState) -> dict[str, Any]:
    """swap.intent 节点。

    出参约定：
    - intent: SwapIntentType 之一（小写下划线）
    - trace: 单条 TraceEntry，记录 LLM 输出 + 实际加载的 prompt name（含灰度版本号）
    """
    if has_confirm_order_keyword(state.get("raw_text")):
        return {
            "intent": "confirm_order",
            "trace": [
                TraceEntry(
                    node="swap_intent",
                    decision="intent=confirm_order rule=has_confirmation_keyword",
                    llm_output={"type": "confirm_order", "prompt_name": None},
                )
            ],
        }

    messages, prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(SwapIntentOutput)
    result: Any = await llm.ainvoke(messages)

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


__all__ = ["CONFIRM_ORDER_KEYWORDS", "has_confirm_order_keyword", "swap_intent"]
