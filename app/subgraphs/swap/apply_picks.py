"""swap.apply_picks 汇合节点（ADR 0024 重构 3）。

swap.select_counterparty ‖ swap.select_ticker 并行产出指针后，在这里做确定性查表覆盖：
- 对手指针 → apply_counterparty（字母 / 序号 / 名称 → swap_counterparties 查表）
- 标的指针 → apply_underlying（seq / directRef → quote_ticker_candidates 查表）
覆盖非破坏：无信号 / 空指针 / 解析不到 → 保留 swap.place_order 抽取的原值。
用完清空两个指针通道，避免跨轮残留。
"""
from __future__ import annotations

from typing import Any

from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry
from app.subgraphs.swap.aggregate import apply_counterparty, apply_underlying


@safe_node
async def swap_apply_picks(state: AgentState) -> dict[str, Any]:
    place_params = state.get("place_params") or {}
    order_list = [dict(item) for item in (place_params.get("orderList") or [])]

    cp = state.get("swap_counterparty_picks") or {}
    apply_counterparty(
        order_list,
        bool(cp.get("hasSignal")),
        list(cp.get("picks") or []),
        state.get("swap_counterparties") or [],
    )
    ticker_picks = list(state.get("swap_ticker_picks") or [])
    candidate_list = state.get("quote_ticker_candidates") or []
    if ticker_picks and candidate_list:
        apply_underlying(order_list, ticker_picks, candidate_list)

    return {
        "place_params": validated_place_params(orderList=order_list),
        "swap_counterparty_picks": None,
        "swap_ticker_picks": None,
        "trace": [
            TraceEntry(
                node="swap_apply_picks",
                decision=f"cp_signal={bool(cp.get('hasSignal'))},cp_picks={len(cp.get('picks') or [])},"
                f"ticker_picks={len(ticker_picks)}",
            )
        ],
    }


__all__ = ["swap_apply_picks"]
