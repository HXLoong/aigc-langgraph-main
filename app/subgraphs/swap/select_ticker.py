"""swap.select_ticker 节点 · 互换-选择标的（DSL v2 新节点）。

只判断用户本次 raw_content 是否在切换某订单的候选标的；不抽取标的以外任何
字段，只吐指向 candidate_list 的指针（下游用 seq/directRef 确定性查表拿到真实
windCode）。

只在 place_order_request 分支、且 quote_content 非空且非 "null" 时调用
（图 3-4 段边）；与 swap.select_counterparty 并行（ADR 0024 重构 3）。

输入：raw_text（=raw_content）/ quote_content /
      quote_ticker_candidates（=candidate_list）
输出：state['swap_ticker_picks']（LLM 指针列表；candidate_list 为空 → [] 且跳过 LLM）。
      确定性查表覆盖 placeOrderWindCode 收敛到 swap_apply_picks 汇合节点

LLM：complex 模型（对齐 Dify external-deepseek-v4-pro-non-thinking）+
     with_structured_output（ADR 0010）。
prompt：app/prompts/swap/select_ticker.md（Dify 原文）。
"""
from __future__ import annotations

import json
from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts.spec import PromptSpec, register
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


SPEC = register(PromptSpec(
    category="swap",
    name="select_ticker",
    output_model=SwapSelectTickerOutput,
    inputs=("raw_text", "quote_content", "quote_ticker_candidates"),
    user_builder=_build_user_message,
))


@safe_node
async def swap_select_ticker(state: AgentState) -> dict[str, Any]:
    """swap.select_ticker 节点。

    只产出 LLM 指针到 state['swap_ticker_picks']；覆盖草稿的确定性查表在
    swap_apply_picks 完成。
    """
    candidate_list = state.get("quote_ticker_candidates") or []

    if not candidate_list:
        # candidate_list 为空 → 不可能切标的，跳过 LLM 调用
        return {
            "swap_ticker_picks": [],
            "trace": [
                TraceEntry(
                    node="swap_select_ticker",
                    decision="skipped:no_candidate_list",
                )
            ],
        }

    llm = get_qwen_complex().with_structured_output(SwapSelectTickerOutput)
    messages, _prompt_name = SPEC.build_messages(state)
    result: Any = await llm.ainvoke(messages)

    return {
        "swap_ticker_picks": [p.model_dump() for p in result.picks],
        "trace": [
            TraceEntry(
                node="swap_select_ticker",
                decision=f"picks={len(result.picks)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_select_ticker"]
