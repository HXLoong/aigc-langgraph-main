"""Literal choices are resolved only inside one unambiguous current order."""
import re

from app.graph.state import AgentState
from app.subgraphs.swap.models import (
    SwapCounterpartyPick,
    SwapSelectCounterpartyOutput,
    SwapSelectTickerOutput,
    SwapTickerPick,
)


def counterparty_choice(state: AgentState) -> SwapSelectCounterpartyOutput | None:
    candidates = state.get("swap_counterparties") or []
    if not candidates:
        return SwapSelectCounterpartyOutput()
    orders = (state.get("place_params") or {}).get("orderList") or []
    if len(orders) != 1:
        return None
    raw = (state.get("raw_text") or "").strip()
    literal = re.sub(r"^(?:交易对手|对手|选择|选)\s*[:：]?\s*", "", raw)
    matches = [c for c in candidates if raw == c.get("shortName") or literal == c.get("shortName")
               or (re.fullmatch(r"[A-Za-z]", literal) and literal.upper() == str(c.get("sort") or "").upper())]
    names = {c["shortName"] for c in matches if c.get("shortName")}
    if len(names) != 1:
        return None
    return SwapSelectCounterpartyOutput(hasSignal=True, picks=[SwapCounterpartyPick(
        idx=0, orderId=orders[0].get("orderId"), directName=next(iter(names)),
        letter=literal.upper() if re.fullmatch(r"[A-Za-z]", literal) else None,
    )])


def ticker_choice(state: AgentState) -> SwapSelectTickerOutput | None:
    orders = (state.get("place_params") or {}).get("orderList") or []
    if len(orders) != 1:
        return None
    blocks = state.get("quote_ticker_candidates") or []
    matching = [b for b in blocks if b.get("orderId") == orders[0].get("orderId")]
    if len(matching) == 1:
        block = matching[0]
    elif len(blocks) == 1 and not blocks[0].get("orderId"):
        block = blocks[0]
    else:
        return None
    literal = re.sub(r"^(?:选择|选|标的)\s*[:：]?\s*", "", (state.get("raw_text") or "").strip())
    matches = [c for c in block.get("candidates") or [] if literal and (
        literal == str(c.get("seq")) or literal == c.get("name")
        or literal.upper() == str(c.get("code") or "").upper()
    )]
    if len(matches) != 1:
        return None
    return SwapSelectTickerOutput(picks=[SwapTickerPick(
        idx=0, orderId=orders[0].get("orderId"), seq=matches[0].get("seq"),
        directRef=matches[0].get("code"),
    )])
