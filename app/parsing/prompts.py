"""四种互斥解析配置；每次调用只选择一个 PromptSpec。"""

from __future__ import annotations

from app.graph.state import AgentState
from app.parsing.models import (
    CloseInstruction,
    CrossProductInstruction,
    OptionInstruction,
    SwapInstruction,
)
from app.prompts import blocks
from app.prompts.spec import PromptSpec, register


def build_user_message(state: AgentState) -> str:
    """向模型提供原文、引用、附件位置与授权上下文，不在代码中拼业务规则。"""
    context = {
        **(state.get("parse_context") or {}),
        "product_hint": state.get("product_type"),
        "option_counterparties": state.get("option_counterparties") or [],
        "swap_counterparties": state.get("swap_counterparties") or [],
        "quote_ticker_candidates": state.get("quote_ticker_candidates") or [],
        "attachment_rows": state.get("attachment_rows") or [],
    }
    return blocks.source_payload(
        state, context=context, attachments=state.get("attachment_sources") or {}
    )


_INPUTS = (
    "raw_text",
    "quote_content",
    "history_messages",
    "product_type",
    "parse_context",
    "option_counterparties",
    "swap_counterparties",
    "quote_ticker_candidates",
    "attachment_sources",
    "attachment_rows",
    "conversation_id",
)

# 已知产品的 schema 不包含其它产品参数；只有跨产品配置使用判别联合类型。
SPECS = {
    "option": register(
        PromptSpec(
            category="option",
            name="parse_instruction",
            output_model=OptionInstruction,
            inputs=_INPUTS,
            user_builder=build_user_message,
            gray=True,
        )
    ),
    "swap": register(
        PromptSpec(
            category="swap",
            name="parse_instruction",
            output_model=SwapInstruction,
            inputs=_INPUTS,
            user_builder=build_user_message,
            gray=True,
        )
    ),
    "option_close": register(
        PromptSpec(
            category="option_close",
            name="parse_instruction",
            output_model=CloseInstruction,
            inputs=_INPUTS,
            user_builder=build_user_message,
            gray=True,
        )
    ),
    "unknown": register(
        PromptSpec(
            category="router",
            name="parse_instruction",
            output_model=CrossProductInstruction,
            inputs=_INPUTS,
            user_builder=build_user_message,
            gray=True,
        )
    ),
}
