"""Validate scoped selection evidence and lock only authoritative candidate identities."""
from __future__ import annotations

from typing import Any

from app.extraction.fields import FieldRecord
from app.graph.business_params import validated_place_params
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TickerCandidate, TraceEntry
from app.subgraphs.swap.selection_rules import validate_picks
from app.subgraphs.ticker.resolver import _code_identity


@safe_node
async def swap_apply_picks(state: AgentState) -> dict[str, Any]:
    place_params = state.get("place_params") or {}
    orders = [dict(item) for item in place_params.get("orderList") or []]
    cp = state.get("swap_counterparty_picks") or {}
    if cp.get("picks") and not cp.get("hasSignal"):
        raise ValueError("对手选择信号与指针不一致")
    cp_picks = validate_picks(state, list(cp.get("picks") or []), "counterparty")
    ticker_picks = validate_picks(state, list(state.get("swap_ticker_picks") or []), "ticker")
    tickers = [TickerCandidate.model_validate(ticker) for ticker in state.get("tickers") or []]
    records: dict[str, FieldRecord] = {}
    for field, picks in (("placeOrderShortname", cp_picks), ("placeOrderWindCode", ticker_picks)):
        for pick in picks:
            index = pick["idx"]
            value = pick["directName"] if field == "placeOrderShortname" else pick["directRef"]
            if field == "placeOrderWindCode":
                market = orders[index].get("placeOrderTransactionType")
                codes = {ticker.wind_code for ticker in tickers
                         if ticker.from_goats and _code_identity(ticker.wind_code) == _code_identity(value)
                         and (not market or market in ticker.transaction_type_lists)}
                if len(codes) != 1:
                    raise ValueError("所选标的缺少唯一 GOATS 校验结果")
                value = next(iter(codes))
            path = f"swap/place_order.orderList.{index}.{field}"
            previous = (state.get("field_records") or {}).get(path)
            if previous is not None and previous.locked and previous.value != value:
                raise ValueError("已锁定字段不能在同一指令中被选择节点改写")
            if previous is not None:
                records[path + ".candidate"] = previous
            selection_path = path + ".selection"
            records[selection_path] = FieldRecord(
                value=pick, source="user", evidence=pick["evidence"], origin="raw",
                confidence=pick["confidence"], locked=True,
            )
            records[path] = FieldRecord(
                value=value, source="goats", evidence=value, locked=True,
                origin="authorized-counterparties" if field == "placeOrderShortname" else "securities-instrument",
                derived_from=[selection_path],
            )
            orders[index][field] = value
    return {
        "place_params": validated_place_params(orderList=orders),
        "field_records": records,
        "swap_counterparty_picks": None,
        "swap_ticker_picks": None,
        "trace": [TraceEntry(node="swap_apply_picks", decision=f"cp_picks={len(cp_picks)},ticker_picks={len(ticker_picks)}")],
    }


__all__ = ["swap_apply_picks"]
