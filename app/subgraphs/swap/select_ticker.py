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

from app.graph.retry import io_node
from app.graph.state import AgentState, TickerCandidate, TraceEntry
from app.llm.clients import get_qwen_complex
from app.prompts.spec import PromptSpec, register
from app.subgraphs.swap.models import SwapSelectTickerOutput
from app.subgraphs.swap.selection_rules import ticker_choice, validate_picks
from app.subgraphs.ticker.resolver import _code_identity
from app.subgraphs.ticker.tools import _make_client
from app.tools.ticker_client import KeywordItem, SecuritiesInstrumentReqVO


def _build_user_message(state: AgentState) -> str:
    raw_content = state.get("raw_text", "") or ""
    quote_content = state.get("quote_content") or ""
    candidate_list = state.get("quote_ticker_candidates") or []
    candidate_list_str = json.dumps(candidate_list, ensure_ascii=False)
    return (
        f"raw_content：{raw_content}\n"
        f"quote_content：{quote_content}\n"
        f"candidate_list：{candidate_list_str}\n"
        f"orders：{state.get('place_params') or {}}"
    )


SPEC = register(PromptSpec(
    category="swap",
    name="select_ticker",
    output_model=SwapSelectTickerOutput,
    inputs=("raw_text", "quote_content", "quote_ticker_candidates", "place_params"),
    user_builder=_build_user_message,
))


async def _verify_selected_codes(state: AgentState, picks: list[dict[str, Any]]) -> list[TickerCandidate]:
    verified = [TickerCandidate.model_validate(item) for item in state.get("tickers") or []]
    verified = [ticker for ticker in verified if ticker.from_goats]
    known = {_code_identity(ticker.wind_code) for ticker in verified}
    requested = {pick["directRef"] for pick in picks}
    missing = [code for code in requested if _code_identity(code) not in known]
    if missing:
        rows = await _make_client().search_securities_instrument(SecuritiesInstrumentReqVO(
            keywordItems=[KeywordItem(keyword=code, isFull=True) for code in sorted(missing)],
        ))
        missing_identities = {_code_identity(code) for code in missing}
        verified.extend(TickerCandidate.model_validate({**row, "from_goats": True})
                        for row in rows if isinstance(row.get("windCode"), str)
                        and _code_identity(row["windCode"]) in missing_identities)
    orders = (state.get("place_params") or {}).get("orderList") or []
    for pick in picks:
        market = orders[pick["idx"]].get("placeOrderTransactionType")
        matches = [ticker for ticker in verified
                   if _code_identity(ticker.wind_code) == _code_identity(pick["directRef"])
                   and (not market or market in ticker.transaction_type_lists)]
        if not matches:
            raise ValueError("所选标的未通过 GOATS 与市场校验")
    return verified


@io_node
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

    result = ticker_choice(state)
    method = "code" if result is not None else "llm"
    if result is None:
        llm = get_qwen_complex().with_structured_output(SwapSelectTickerOutput)
        messages, _prompt_name = SPEC.build_messages(state)
        result = SwapSelectTickerOutput.model_validate(await llm.ainvoke(messages))

    picks = validate_picks(state, [pick.model_dump() for pick in result.picks], "ticker")
    verified = await _verify_selected_codes(state, picks) if picks else state.get("tickers") or []
    return {
        "swap_ticker_picks": picks,
        "tickers": verified,
        "trace": [
            TraceEntry(
                node="swap_select_ticker",
                decision=f"{method},picks={len(result.picks)}",
                llm_output=result.model_dump(),
            )
        ],
    }


__all__ = ["swap_select_ticker"]
