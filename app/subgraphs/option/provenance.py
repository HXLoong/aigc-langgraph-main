"""Bind deterministic parser records to the same ordered DTOs sent to Java."""
from __future__ import annotations

from typing import Any

from app.extraction.fields import FieldRecord, merge_fields
from app.extraction.locks import protect_orders
from app.graph.state import AgentState
from app.subgraphs.option.models import OptionOrderItemWithFastExec
from app.subgraphs.option.place_params import ParsedPlaceParams


def use_memory_orders(parsed: ParsedPlaceParams, order_ids: list[str]) -> None:
    """Remembered IDs are attributed to the actual memory slot, never fabricated raw text."""
    original, fields = parsed.orders[0], parsed.fields[0]
    parsed.orders = [{**original, "order_id": order_id} for order_id in order_ids]
    parsed.fields = [
        {**fields, "order_id": FieldRecord(
            value=order_id, source="inferred", evidence=f"last_confirmed_params.order_ids[{index}]",
            origin="memory:last_confirmed_params", locked=True,
        )}
        for index, order_id in enumerate(order_ids)
    ]


def prepare_order_provenance(
    state: AgentState, parsed: ParsedPlaceParams, orders: list[dict[str, Any]], *, scope: str,
) -> tuple[AgentState, list[dict[str, Any]], dict[str, FieldRecord]]:
    records: dict[str, FieldRecord] = {}
    for index, fields in enumerate(parsed.fields):
        for key, record in fields.items():
            name, separator, detail = key.partition(".")
            info = OptionOrderItemWithFastExec.model_fields[name]
            alias = info.alias or name
            path = f"{scope}.orderList.{index}.{alias}"
            if separator:
                path += "." + detail
            records[path] = record
    prepared: AgentState = {**state, "field_records": merge_fields(state.get("field_records"), records)}
    protected, rejected = protect_orders(prepared, orders, product="option")
    return prepared, protected, {**records, **rejected}
