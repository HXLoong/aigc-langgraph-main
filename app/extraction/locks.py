"""Apply the field ledger at both state writes and the external side-effect boundary."""
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.extraction.fields import FieldRecord


def protect_orders(
    state: Mapping[str, Any], orders: list[dict[str, Any]], *, product: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, FieldRecord]]:
    protected = deepcopy(orders)
    rejected: dict[str, FieldRecord] = {}
    for path, record in (state.get("field_records") or {}).items():
        if not isinstance(record, FieldRecord) or not record.locked or ".orderList." not in path:
            continue
        scope, tail = path.split(".orderList.", 1)
        if product and not scope.startswith(product + "/"):
            continue
        parts = tail.split(".")
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        index, field = int(parts[0]), parts[1]
        if index >= len(protected):
            raise ValueError("locked order cannot be removed within the current instruction")
        attempted = protected[index].get(field)
        if attempted != record.value:
            # The reducer records this rejected proposal while preserving the locked value.
            rejected[path] = record.model_copy(update={"value": attempted})
            protected[index][field] = record.value
    return protected, rejected


def protect_update(state: Mapping[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    params = update.get("place_params")
    if not isinstance(params, dict) or not isinstance(params.get("orderList"), list):
        return update
    orders, rejected = protect_orders(state, params["orderList"])
    if rejected:
        update = {**update, "place_params": {**params, "orderList": orders},
                  "field_records": {**(update.get("field_records") or {}), **rejected}}
    return update
