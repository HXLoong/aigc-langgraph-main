"""swap.select_counterparty 节点 · 互换-选择交易对手（DSL v2 新节点）。

只判断用户本次 raw_content 是否在选交易对手、补到哪笔订单；不抽取对手以外任何
字段，只吐 字母/序号/名称 指针（下游按 sort 确定性查表拿到真实 shortName）。

只在 place_order_request 分支、且 quote_content 非空且非 "null" 时调用
（图 3-4 段边——`swap.graph._route_after_swap_place_order`）。

输入：raw_text（=raw_content）/ swap_counterparties（=shortname_list）/
      quote_content
输出：state['place_params']（orderList[i].placeOrderShortname 被指针覆盖，
      非破坏——LLM 无信号或解析空时保留 swap.place_order 抽取的原值）

LLM：complex 模型（对齐 Dify external-deepseek-v4-pro-non-thinking）+
     with_structured_output（ADR 0010）。
prompt：app/prompts/swap/select_counterparty.md（Dify 原文）。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts import load_prompt
from app.subgraphs.swap.aggregate import apply_counterparty
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


@safe_node
async def swap_select_counterparty(state: AgentState) -> dict[str, Any]:
    """swap.select_counterparty 节点。

    读取 state['place_params']['orderList']（swap.place_order 已产出的草稿），
    用 LLM 指针 + swap_counterparties 确定性查表覆盖 placeOrderShortname，
    写回 state['place_params']。
    """
    prompt = load_prompt("swap", "select_counterparty")
    llm = get_qwen_complex().with_structured_output(SwapSelectCounterpartyOutput)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    place_params = state.get("place_params") or {}
    order_list = [dict(item) for item in (place_params.get("orderList") or [])]
    trs_list = state.get("swap_counterparties") or []

    apply_counterparty(
        order_list,
        result.hasSignal,
        [p.model_dump() for p in result.picks],
        trs_list,
    )

    return {
        "place_params": validated_place_params(
            expected_action=place_params.get("expected_action", ""),
            orderList=order_list,
        ),
        "trace": [
            TraceEntry(
                node="swap_select_counterparty",
                decision=f"hasSignal={result.hasSignal},picks={len(result.picks)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_select_counterparty"]
