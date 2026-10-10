"""Apply the field ledger at both state writes and the external side-effect boundary."""
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.extraction.fields import FieldRecord, merge_fields


def _effective_records(state: Mapping[str, Any]) -> dict[str, FieldRecord]:
    """已验证选择派生的有效锁替代原始候选锁，原始账本仍完整保留。"""
    records = dict(state.get("field_records") or {})
    superseded: set[str] = set()
    for path, record in records.items():
        if not isinstance(record, FieldRecord) or not record.locked:
            continue
        prefix = "swap/place_order.orderList."
        if not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split(".")
        if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in {
            "placeOrderWindCode", "placeOrderShortname",
        }:
            continue
        candidate_path = f"swap/parse.orderList.{parts[0]}.{parts[1]}"
        selection_path = path + ".selection"
        candidate = records.get(candidate_path)
        selection = records.get(selection_path)
        snapshot = records.get(path + ".candidate")
        value_key = "directRef" if parts[1] == "placeOrderWindCode" else "directName"
        if (
            isinstance(candidate, FieldRecord) and candidate.locked
            and snapshot == candidate
            and candidate_path in record.derived_from
            and selection_path in record.derived_from
            and isinstance(selection, FieldRecord) and selection.locked
            and selection.source == "user" and selection.origin == "raw"
            and selection.evidence and selection.evidence in (state.get("raw_text") or "")
            and isinstance(selection.value, dict)
            and selection.value.get("idx") == int(parts[0])
            and selection.value.get(value_key) == record.value
        ):
            superseded.add(candidate_path)
    return {path: record for path, record in records.items() if path not in superseded}


def protect_orders(
    state: Mapping[str, Any], orders: list[dict[str, Any]], *, product: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, FieldRecord]]:
    protected = deepcopy(orders)
    rejected: dict[str, FieldRecord] = {}
    for path, record in _effective_records(state).items():
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
    for key, list_key, product in (("place_params", "orderList", None),
                                   ("close_params", "closeOrderList", "close")):
        params = update.get(key)
        if not isinstance(params, dict) or not isinstance(params.get(list_key), list):
            continue
        # 选择节点在本次更新中新增有效锁，必须与参数一起投影后再做锁保护。
        current = {**state, "field_records": merge_fields(
            state.get("field_records"), update.get("field_records"),
        )}
        orders, rejected = protect_orders(current, params[list_key], product=product)
        if rejected:
            update = {**update, key: {**params, list_key: orders},
                      "field_records": {**(update.get("field_records") or {}), **rejected}}
    return update
