"""swap.select_ticker 节点 · 互换-选择标的（DSL v2 新节点）。

只判断用户本次 raw_content 是否在切换某订单的候选标的；不抽取标的以外任何
字段，只吐指向 candidate_list 的指针（下游用 seq/directRef 确定性查表拿到真实
windCode）。

只在 place_order_request 分支、且 quote_content 非空且非 "null" 时调用
（图 3-4 段边）；swap.select_counterparty 之后顺序执行（LangGraph 并行非必需）。

输入：raw_text（=raw_content）/ quote_content /
      quote_ticker_candidates（=candidate_list）
输出：state['place_params']（orderList[i].placeOrderWindCode 被指针覆盖，
      非破坏——candidate_list 为空、或 LLM 未切换/解析空时保留原值）

LLM：complex 模型（对齐 Dify external-deepseek-v4-pro-non-thinking）+
     with_structured_output（ADR 0010）。
prompt：app/prompts/swap/select_ticker.md（Dify 原文）。
"""
from __future__ import annotations

import json
from typing import Any

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts import load_prompt
from app.subgraphs.swap.aggregate import apply_underlying
from app.subgraphs.swap.models import SwapSelectTickerOutput


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    candidate_list = state.get("quote_ticker_candidates") or []
    candidate_list_str = json.dumps(candidate_list, ensure_ascii=False)
    return (
        f"raw_content：{raw_content}\n"
        f"quote_content：{quote_content}\n"
        f"candidate_list：{candidate_list_str}"
    )


@safe_node
async def swap_select_ticker(state: AgentState) -> dict[str, Any]:
    """swap.select_ticker 节点。

    读取 state['place_params']['orderList']（swap.place_order / 已经过
    swap.select_counterparty 覆盖的草稿），用 LLM 指针 +
    quote_ticker_candidates 确定性查表覆盖 placeOrderWindCode，写回
    state['place_params']。
    """
    candidate_list = state.get("quote_ticker_candidates") or []

    place_params = state.get("place_params") or {}
    order_list = [dict(item) for item in (place_params.get("orderList") or [])]

    if not candidate_list:
        # Dify 原节点语义：candidate_list 为空 → 不可能切标的，跳过 LLM 调用
        return {
            "place_params": validated_place_params(
                expected_action=place_params.get("expected_action", ""),
                orderList=order_list,
            ),
            "trace": [
                TraceEntry(
                    node="swap_select_ticker",
                    decision="skipped:no_candidate_list",
                )
            ],
        }

    prompt = load_prompt("swap", "select_ticker")
    llm = get_qwen_complex().with_structured_output(SwapSelectTickerOutput)

    user_message = _build_user_message(state)
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_message),
        ]
    )

    apply_underlying(order_list, [p.model_dump() for p in result.picks], candidate_list)

    return {
        "place_params": validated_place_params(
            expected_action=place_params.get("expected_action", ""),
            orderList=order_list,
        ),
        "trace": [
            TraceEntry(
                node="swap_select_ticker",
                decision=f"picks={len(result.picks)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_select_ticker"]
