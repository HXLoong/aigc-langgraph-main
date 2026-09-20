"""Constrain model claims to the current operation and explicit source windows."""
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

_ORDER_ID = re.compile(r"H-[0-9]{8}-[0-9]+")
_TERMINATOR = re.compile(r"[,，]\s*全部清仓(?=$|\s|[,，。;；!?！？])")


def _within(cell: Any, text: str) -> bool:
    return isinstance(cell, dict) and bool(cell.get("value")) and bool(cell.get("evidence")) and cell["evidence"] in text


def constrain_candidates(candidates: BaseModel, sources: Mapping[str, str]) -> BaseModel:
    data = candidates.model_dump(by_alias=True)
    orders = data.get("orderList") or []
    raw, quote = sources.get("raw", ""), sources.get("quote", "")
    if _ORDER_ID.search(quote):
        for order in orders:
            for field, cell in order.items():
                if field not in {"orderId", "placeOrderUltraContractCode"} and cell and cell.get("origin") != "raw":
                    order[field] = None
            # Bare option/number replies are interpreted by the explicit selection chain.
            if re.fullmatch(r"[0-9]+|[A-Za-z](?:[、,，\s]+[A-Za-z])*", raw.strip()):
                order["placeOrderWindCode"] = None
        return type(candidates).model_validate(data)
    match = _TERMINATOR.search(raw)
    if not match:
        return candidates
    prefix = raw[:match.start()]
    eligible = [order for order in orders if any(
        _within(order.get(field), prefix) for field in ("placeOrderQuantity", "placeOrderNotional")
    ) and all(
        not order.get(field) or _within(order[field], prefix)
        for field in ("placeOrderWindCode", "placeOrderOrderDirection")
    )]
    if len(eligible) < 2:
        return candidates
    for order in eligible:
        for field, cell in order.items():
            if field != "placeOrderShortname" and cell and not _within(cell, prefix):
                order[field] = None
    data["orderList"] = eligible
    return type(candidates).model_validate(data)
