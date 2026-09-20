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

from app.execution.confirmation import (
    confirmation_action,
    confirmation_attempt,
)
from app.extraction.intent_evidence import intent_records, source_payload
from app.graph.retry import io_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_thinking
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.confirmation import is_confirmation
from app.subgraphs.swap.models import SwapIntentOutput


def has_confirm_order_keyword(raw: str | None) -> bool:
    """兼容旧函数名；完整匹配 CWAIJY-957 确认口令。"""
    return is_confirmation(raw)


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
    inputs=("raw_text", "quote_content", "history_messages", "swap_counterparties", "conversation_id"),
    user_builder=lambda state: _build_user_message(state) + "\n" + source_payload(state),
    gray=True,
))


@io_node
async def swap_intent(state: AgentState) -> dict[str, Any]:
    """swap.intent 节点。

    出参约定：
    - intent: SwapIntentType 之一（小写下划线）
    - trace: 单条 TraceEntry，记录 LLM 输出 + 实际加载的 prompt name（含灰度版本号）
    """
    raw = state.get("raw_text")
    action = confirmation_action(raw)
    if confirmation_attempt(raw):
        intent = {"place": "confirm_order", "cancel": "confirm_cancel_order", "modify": "confirm_modify_order"}.get(action or "", "unknown_intent")
        return {"intent": intent, "trace": [TraceEntry(node="swap_intent", decision=f"confirmation:{intent}")]}

    messages, prompt_name = SPEC.build_messages(state)
    llm = get_qwen_thinking().with_structured_output(SwapIntentOutput)
    result = SwapIntentOutput.model_validate(await llm.ainvoke(messages))
    records = intent_records(result, state, scope="swap/intent", value=result.type)

    return {
        "intent": result.type,
        "field_records": records,
        "trace": [
            TraceEntry(
                node="swap_intent",
                decision=f"intent={result.type} prompt={prompt_name}",
                llm_output={"type": result.type, "prompt_name": prompt_name, "confidence": result.confidence, "evidence_count": len(result.evidence)},
            )
        ],
    }


__all__ = ["has_confirm_order_keyword", "swap_intent"]
