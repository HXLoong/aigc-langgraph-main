"""Code-owned identity provenance and protection for ordered DTOs and close ID arrays."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from app.extraction.fields import FieldRecord, merge_fields
from app.extraction.locks import protect_orders

if TYPE_CHECKING:  # 仅类型标注；运行时不依赖 app.graph（graph.state 依赖 extraction.fields）
    from app.graph.state import AgentState

CLOSE_ID_ARRAYS = frozenset({"confirmOrderNoList", "cancelOrderNoList", "confirmCancelOrderNoList", "queryOrderNoList"})


def protect_identity_lists(
    state: Mapping[str, Any], payload: dict[str, Any], *, product: str = "close",
) -> tuple[dict[str, Any], dict[str, FieldRecord]]:
    """Final backend boundary hook; protect actual named arrays, not synthetic orderList rows."""
    protected = deepcopy(payload)
    rejected: dict[str, FieldRecord] = {}
    for path, record in (state.get("field_records") or {}).items():
        if not isinstance(record, FieldRecord) or not record.locked or not path.startswith(product + "/"):
            continue
        parts = path.split(".")
        if len(parts) != 3 or parts[1] not in CLOSE_ID_ARRAYS or not parts[2].isdigit():
            continue
        field, index = parts[1], int(parts[2])
        ids = protected.get(field) or []
        if index >= len(ids):
            raise ValueError("locked identity cannot be removed within the current instruction")
        if ids[index] != record.value:
            rejected[path] = record.model_copy(update={"value": ids[index]})
            ids[index] = record.value
    return protected, rejected


def prepare_identity_scope(
    state: AgentState, order_ids: Sequence[str | None], *, scope: str, origin: str,
    evidence: str, field: str = "orderList", explicit_raw_ids: Sequence[str] = (),
    selection: bool = False,
) -> tuple[AgentState, list[str | None], dict[str, FieldRecord]]:
    """Caller supplies the source branch selected by its existing product parser."""
    records: dict[str, FieldRecord] = {}
    raw = state.get("raw_text") or ""
    for index, order_id in enumerate(order_ids):
        if order_id is None:
            continue  # Java's default recent-order query is not a user-supplied identity.
        identity_origin, identity_evidence = origin, evidence
        if order_id in explicit_raw_ids:
            identity_origin, identity_evidence = "raw", raw
        path = f"{scope}.{field}.{index}" + (".orderId" if field == "orderList" else "")
        records[path] = FieldRecord(
            value=order_id, source="inferred" if identity_origin.startswith("memory:") else "user",
            evidence=identity_evidence, origin=identity_origin, locked=True,
        )
        if selection and raw:
            records[path + ".selection"] = FieldRecord(
                value=raw, source="user", evidence=raw, origin="raw", locked=True,
            )
    prepared: AgentState = {**state, "field_records": merge_fields(state.get("field_records"), records)}
    if field == "orderList":
        protected, rejected = protect_orders(
            prepared, [{"orderId": order_id} for order_id in order_ids], product=scope.split("/", 1)[0],
        )
        ids = [order["orderId"] for order in protected]
    else:
        payload, rejected = protect_identity_lists(prepared, {field: list(order_ids)})
        ids = payload[field]
    return prepared, ids, {**records, **rejected}
