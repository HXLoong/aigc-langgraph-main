"""Capture validated DTOs, batch compatible lists, and submit each batch once."""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from app.tools.exceptions import BackendUnreachableError
from app.tools.option_client import FinancialOrderOpenApiSaveReqVO, OptionClientHttpx
from app.tools.receipts import receipt_update
from app.tools.swap_client import SwapClientHttpx, SwapOrderOpenApiSaveReqVO

Product = Literal["swap", "option", "close"]
_LIST_FIELDS = ("closeOrderList", "confirmOrderNoList", "cancelOrderNoList",
                "confirmCancelOrderNoList", "queryOrderNoList")


@dataclass
class Preparation:
    identity: dict[str, Any]
    allowed_order_ids: set[str] | None = None
    dependency_product: str | None = None
    operations: list[dict[str, Any]] = field(default_factory=list)


_PREPARATION: ContextVar[Preparation | None] = ContextVar("instruction_preparation", default=None)


@contextmanager
def capture_operations(
    identity: dict[str, Any], *, allowed_order_ids: set[str] | None = None,
    dependency_product: str | None = None,
) -> Iterator[Preparation]:
    preparation = Preparation(identity=identity, allowed_order_ids=allowed_order_ids,
                              dependency_product=dependency_product)
    token = _PREPARATION.set(preparation)
    try:
        yield preparation
    finally:
        _PREPARATION.reset(token)


def _order_ids(payload: Any) -> set[str]:
    if isinstance(payload, list):
        return set().union(*(_order_ids(item) for item in payload))
    if not isinstance(payload, dict):
        return set()
    result: set[str] = set()
    for key, value in payload.items():
        if key == "orderId" and isinstance(value, str) and value:
            result.add(value)
        elif key in {"confirmOrderNoList", "cancelOrderNoList", "confirmCancelOrderNoList", "queryOrderNoList"}:
            result.update(item for item in value or [] if isinstance(item, str))
        else:
            result.update(_order_ids(value))
    return result


def capture_operation(product: Product, request: BaseModel) -> bool:
    """True means preparation only; callers must not invoke the business client."""
    preparation = _PREPARATION.get()
    if preparation is None:
        return False
    payload = request.model_dump(mode="json", exclude_none=True)
    for key, expected in preparation.identity.items():
        if payload.get(key) != expected:
            raise ValueError("sub-instruction changed the original message ownership")
    if preparation.allowed_order_ids is not None:
        if preparation.dependency_product != ("option_close" if product == "close" else product):
            raise ValueError("dependency order belongs to a different product")
        selected = _order_ids(payload)
        bindable = {"query_order_status", "cancel_order_request", "request_cancel_order",
                    "place_order_from_quote"}
        orders = payload.get("orderList") or []
        if (not selected and len(preparation.allowed_order_ids) == 1
            and payload.get("type") in bindable and len(orders) == 1
            and isinstance(orders[0], dict) and not orders[0].get("orderId")):
            orders[0]["orderId"] = next(iter(preparation.allowed_order_ids))
            selected = _order_ids(payload)
        if not selected or not selected.issubset(preparation.allowed_order_ids):
            raise ValueError("dependency order selection is unresolved or broader than its evidence")
    preparation.operations.append({"product": product, "payload": deepcopy(payload)})
    return True


def dedup_key(operation: dict[str, Any]) -> str:
    payload = operation["payload"]
    prefix = "swap:" if operation["product"] == "swap" else ""
    return f"{prefix}{payload['userId']}:{payload['type']}:{payload['messageId']}"


def _common(operation: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(operation["payload"])
    for key in ("rawContent", "messageContent", "orderList"):
        payload.pop(key, None)
    close = payload.get("closeOrderReqVO")
    if isinstance(close, dict):
        for key in _LIST_FIELDS:
            close.pop(key, None)
    return {"product": operation["product"], "payload": payload}


def _joinable(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _common(left) != _common(right):
        return False
    # CWAIJY-957 validates each original confirmation phrase; concatenating two
    # phrases would create a different confirmation protocol request.
    if "confirm" in left["payload"]["type"]:
        return False
    a, b = left["payload"], right["payload"]
    if a.get("orderList") and b.get("orderList"):
        # Java removes repeated object/order IDs. Separate these requests so that
        # a second explicit instruction is neither discarded nor silently changed.
        ids_a, ids_b = _order_ids(a["orderList"]), _order_ids(b["orderList"])
        return not (ids_a & ids_b or any(item in a["orderList"] for item in b["orderList"]))
    ca, cb = a.get("closeOrderReqVO"), b.get("closeOrderReqVO")
    if isinstance(ca, dict) and isinstance(cb, dict):
        active_a = {key for key in _LIST_FIELDS if ca.get(key)}
        active_b = {key for key in _LIST_FIELDS if cb.get(key)}
        close_identity_a = {row[key] for row in ca.get("closeOrderList") or []
                            for key in ("orderId", "internalTradeId") if row.get(key)}
        close_identity_b = {row[key] for row in cb.get("closeOrderList") or []
                            for key in ("orderId", "internalTradeId") if row.get(key)}
        if close_identity_a & close_identity_b:
            return False
        return bool(active_a) and active_a == active_b and not any(
            item in ca[key] for key in active_a for item in cb[key]
        )
    return False


def batch_operations(prepared: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for item in prepared:
        operation = deepcopy(item["operation"])
        for batch in batches:
            if not _joinable(batch["operation"], operation):
                continue
            target, source = batch["operation"]["payload"], operation["payload"]
            target.setdefault("orderList", []).extend(source.get("orderList") or [])
            if isinstance(target.get("closeOrderReqVO"), dict):
                for key in _LIST_FIELDS:
                    target["closeOrderReqVO"].setdefault(key, []).extend(
                        source.get("closeOrderReqVO", {}).get(key) or [],
                    )
            target["rawContent"] += "\n" + source["rawContent"]
            target["messageContent"] = target["rawContent"] + (
                "\n" + target["quoteContent"] if target.get("quoteContent") else ""
            )
            batch["instruction_ids"].append(item["instruction_id"])
            break
        else:
            batches.append({"operation": operation, "instruction_ids": [item["instruction_id"]]})
    return batches


async def execute_batches(
    batches: list[dict[str, Any]], *, last_finished: dict[str, float], blocked_keys: set[str],
    dedup_window_seconds: float, clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[dict[str, dict[str, Any]], dict[str, float], set[str]]:
    """Different dedup keys may run concurrently; each key remains ordered, no retries."""
    finished = dict(last_finished)
    blocked = set(blocked_keys)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    results: dict[str, dict[str, Any]] = {}
    for batch in batches:
        groups[dedup_key(batch["operation"])].append(batch)

    async def run_group(key: str, group: list[dict[str, Any]]) -> None:
        for batch in group:
            operation = batch["operation"]
            common: dict[str, Any] = {
                "batch_instruction_ids": list(batch["instruction_ids"]),
                "product_type": "option_close" if operation["product"] == "close" else operation["product"],
                "intent": operation["payload"]["type"],
            }
            if key in blocked:
                result = {**common, "status": "blocked", "reason": "prior_same_key_not_confirmed"}
            else:
                remaining = finished.get(key, float("-inf")) + dedup_window_seconds - clock()
                if remaining > 0:
                    await sleep(remaining)
                operation = batch["operation"]
                payload = operation["payload"]
                try:
                    if operation["product"] == "swap":
                        response = await SwapClientHttpx().operate(SwapOrderOpenApiSaveReqVO.model_validate(payload))
                    else:
                        response = await OptionClientHttpx().operate(FinancialOrderOpenApiSaveReqVO.model_validate(payload))
                    update = receipt_update(response, operation["product"])
                    result = {**common, **update,
                              "status": "response_received" if update["api_code"] == 0 else "failed",
                              "reason": "backend_response"}
                    if result["status"] != "response_received":
                        blocked.add(key)
                except (BackendUnreachableError, httpx.TransportError, TimeoutError):
                    blocked.add(key)
                    result = {**common, "status": "uncertain", "reason": "backend_transport_error"}
                except Exception as exc:  # noqa: BLE001 - each operation keeps its own failure
                    blocked.add(key)
                    # A client exception after dispatch cannot prove that no write occurred.
                    result = {**common, "status": "uncertain", "reason": "backend_result_unavailable",
                              "error_type": type(exc).__name__}
                # Java acquires its dedup key after preprocessing, not at HTTP dispatch.
                # A complete window after receiving the response safely covers that delay.
                finished[key] = clock()
            for instruction_id in batch["instruction_ids"]:
                results[instruction_id] = {"instruction_id": instruction_id, **deepcopy(result)}

    await asyncio.gather(*(run_group(key, group) for key, group in groups.items()))
    return results, finished, blocked


def authoritative_order_id(result: dict[str, Any]) -> str | None:
    """Bind one strict ID from an authentic singleton receipt, never an aggregate scope."""
    if result.get("status") != "response_received" or len(result.get("batch_instruction_ids", [])) != 1:
        return None
    body = result.get("api_result")
    if isinstance(body, dict):
        order_id = body.get("orderId")
        if not isinstance(order_id, str) or not order_id:
            return None
        body = json.dumps(body, ensure_ascii=False)
    if not isinstance(body, str):
        return None
    # Local imports avoid a cycle: subgraph packages import their backend adapters.
    from app.subgraphs.close.order_id import extract_order_ids as close_ids
    from app.subgraphs.option.order_id import extract_order_ids as option_ids
    from app.subgraphs.swap.order_id import extract_order_ids as swap_ids

    by_product = {"swap": swap_ids(body), "option": option_ids(body), "option_close": close_ids(body)}
    all_ids = set().union(*by_product.values())
    candidates = by_product.get(str(result.get("product_type") or ""), [])
    if len(all_ids) != 1 or len(candidates) != 1:
        return None
    order_id = candidates[0]
    if not re.search(rf"(?<![A-Za-z0-9-]){re.escape(order_id)}(?![A-Za-z0-9-])", body):
        return None
    return order_id


def response_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
