"""Option 子图后端调用。"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.execution.operations import capture_operation
from app.extraction.locks import protect_orders
from app.graph.state import AgentState
from app.observability.metrics import (
    emit_option_backend_empty_result,
    emit_option_backend_missing_context,
)
from app.subgraphs.option.sanitize import sanitize_order_list
from app.tools.bot_context import BotContext, normalize_message_id
from app.tools.exceptions import EmptyBackendResultError, MissingBackendContextError
from app.tools.option_client import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    GoatsOptionRfqReqVO,
    OptionClientHttpx,
    OptionIntentionType,
)
from app.tools.receipts import receipt_guard, receipt_update

logger = logging.getLogger(__name__)
#: intent → operate 固定映射（Dify DSL v2：每个 extract 节点的 operate 是单值 enum，
#: 由节点身份决定，不经 LLM 判断——见 spec/llm_schemas.txt 各「期权-节点-*」的
#: operate enum）。未登记的 intent（如 unknown_intent）不传 operate。
_INTENT_TO_OPERATE: dict[str, str] = {
    "new_inquiry": "询价",
    "place_order_from_quote": "交易",
    "confirm_order": "交易",
    "cancel_order_request": "取消",
    "request_cancel_order": "交易",
    "confirm_cancel_order": "交易",
    "query_order_status": "交易",
}


def _message_id(value: Any) -> int:
    return normalize_message_id(value)


def _context(state: AgentState) -> dict[str, Any]:
    """机器人上下文 → Java ReqVO 字段；唯一定义在 app/tools/bot_context.py。"""
    wire = BotContext.from_state(state).to_wire()
    return wire


def _with_resolved_ticker(
    order: dict[str, Any], tickers: list[Any]
) -> tuple[dict[str, Any], str]:
    """Normalize an order by identity; return the order and its binding outcome."""
    stock_code = (order.get("stockCode") or "").strip().upper()
    if not stock_code:
        return order, "missing"
    verified = []
    for ticker in tickers:
        data = ticker if isinstance(ticker, dict) else ticker.model_dump()
        wind_code = data.get("windCode") or ""
        if data.get("from_goats") is not True or not wind_code.strip():
            continue
        verified.append(data)
        if wind_code.strip().upper() == stock_code:
            order["stockCode"] = wind_code
            return order, "matched_code"

    # A qualified code must never be reinterpreted as another instrument's alias,
    # including an unknown exchange suffix that GOATS needs to validate itself.
    if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*\.[A-Z][A-Z0-9]*", stock_code):
        return order, "unmatched"

    matches: dict[str, str] = {}
    for data in verified:
        aliases = [data.get("insShtDesc"), data.get("insLngDesc")]
        aliases.extend(data.get("sourceKeywords") or [])
        if any(isinstance(alias, str) and alias.strip().upper() == stock_code for alias in aliases):
            wind_code = data["windCode"]
            matches[wind_code.strip().upper()] = wind_code
    if len(matches) == 1:
        order["stockCode"] = next(iter(matches.values()))
        return order, "matched_alias"
    if matches:
        return order, "ambiguous"
    return order, "unmatched"


async def call_option_backend(
    state: AgentState,
    *,
    intent: str,
    order_list: list[dict[str, Any]] | None = None,
    option_rfq: dict[str, Any] | None = None,
) -> dict[str, Any]:
    order_list, rejected = protect_orders(state, order_list or [], product="option")
    missing_fields = BotContext.from_state(state).missing_required()
    if missing_fields:
        logger.error(
            "option backend call blocked: missing_fields=%s",
            ",".join(missing_fields),
        )
        emit_option_backend_missing_context()
        raise MissingBackendContextError("option", missing_fields)

    cleaned_order_list = sanitize_order_list(order_list)
    req = FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType(intent),
        operate=_INTENT_TO_OPERATE.get(intent),
        orderList=[
            FinancialOrderOpenApiBaseSaveReqVO.model_validate(item)
            for item in cleaned_order_list
        ],
        optionRfq=(
            GoatsOptionRfqReqVO.model_validate(option_rfq)
            if option_rfq is not None
            else None
        ),
        **_context(state),
    )
    if capture_operation("option", req):
        return {"field_records": rejected} if rejected else {}
    async with receipt_guard("option"):
        result = await OptionClientHttpx().operate(req)
    try:
        update = receipt_update(result, "option")
    except EmptyBackendResultError:
        emit_option_backend_empty_result()
        raise
    return {**({"field_records": rejected} if rejected else {}), **update}
