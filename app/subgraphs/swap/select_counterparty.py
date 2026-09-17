"""swap.select_counterparty 节点 · 互换-选择交易对手（DSL v2 新节点）。

只判断用户本次 raw_content 是否在选交易对手、补到哪笔订单；不抽取对手以外任何
字段，只吐 字母/序号/名称 指针（下游按 sort 确定性查表拿到真实 shortName）。

只在 place_order_request 分支、且 quote_content 非空且非 "null" 时调用
（图 3-4 段边——`swap.graph._route_after_swap_place_order`）。

输入：raw_text（=raw_content）/ swap_counterparties（=shortname_list）/
      quote_content
输出：state['swap_counterparty_picks']（LLM 指针 {hasSignal, picks}）。确定性查表覆盖
      placeOrderShortname 收敛到 swap_apply_picks 汇合节点（ADR 0024 重构 3），本节点
      因而可与 swap.select_ticker 并行

LLM：complex 模型（对齐 Dify external-deepseek-v4-pro-non-thinking）+
     with_structured_output（ADR 0010）。
prompt：app/prompts/swap/select_counterparty.md（Dify 原文）。
"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.models import SwapSelectCounterpartyOutput


def _format_shortname_list(counterparties: list[dict[str, Any]] | None) -> str:
    """[{ctptyId,shortName,longName,sort}] → Dify trsListStr 近似格式。"""
    items = counterparties or []
    if not items:
        return ""
    return ", ".join(
        f"{c.get('sort', '')}:{c.get('shortName', '')}"
        for c in items
        if isinstance(c, dict)
    )


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    shortname_list = _format_shortname_list(state.get("swap_counterparties"))
    quote_content = state.get("quote_content") or ""
    return (
        f"raw_content：{raw_content}\n"
        f"shortname_list：{shortname_list}\n"
        f"quote_content：{quote_content}"
    )


SPEC = register(PromptSpec(
    category="swap",
    name="select_counterparty",
    output_model=SwapSelectCounterpartyOutput,
    inputs=("raw_text", "swap_counterparties", "quote_content"),
    user_builder=_build_user_message,
))


@safe_node
async def swap_select_counterparty(state: AgentState) -> dict[str, Any]:
    """swap.select_counterparty 节点。

    只产出 LLM 指针到 state['swap_counterparty_picks']；覆盖草稿的确定性查表在
    swap_apply_picks 完成。
    """
    llm = get_qwen_complex().with_structured_output(SwapSelectCounterpartyOutput)
    messages, _prompt_name = SPEC.build_messages(state)
    result: Any = await llm.ainvoke(messages)

    return {
        "swap_counterparty_picks": {
            "hasSignal": result.has_signal,
            "picks": [p.model_dump() for p in result.picks],
        },
        "trace": [
            TraceEntry(
                node="swap_select_counterparty",
                decision=f"hasSignal={result.has_signal},picks={len(result.picks)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_select_counterparty"]
