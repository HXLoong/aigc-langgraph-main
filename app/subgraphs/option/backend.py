"""Option 子图后端调用。"""
from __future__ import annotations

from typing import Any

from app.graph.state import AgentState
from app.tools.option_client import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    GoatsOptionRfqReqVO,
    OptionClientHttpx,
    OptionIntentionType,
)


def _message_id(value: Any) -> int:
    if isinstance(value, int):
        return value
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits[-18:]) if digits else 0


def _context(state: AgentState) -> dict[str, Any]:
    raw = state.get("raw_text", "") or ""
    quote = state.get("quote_content")
    return {
        "conversationId": state.get("conversation_id", "") or "",
        "messageId": _message_id(state.get("message_id", 0)),
        "messageContent": raw if not quote else f"{raw}\n{quote}",
        "rawContent": raw,
        "quoteContent": quote,
        "quoteAppinfo": state.get("quote_appinfo"),
        "userId": state.get("user_id", "") or "",
        "roomId": state.get("room_id", "") or "",
        "guid": state.get("guid"),
    }


def _with_resolved_ticker(
    order: dict[str, Any], tickers: list[Any], index: int
) -> dict[str, Any]:
    if index < len(tickers):
        ticker = tickers[index]
        wind_code = getattr(ticker, "windCode", None)
        if wind_code is None and isinstance(ticker, dict):
            wind_code = ticker.get("windCode")
        if wind_code:
            order["stockCode"] = wind_code
    return order


async def call_option_backend(
    state: AgentState,
    *,
    intent: str,
    order_list: list[dict[str, Any]] | None = None,
    option_rfq: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not state.get("conversation_id") or not state.get("room_id") or not state.get("user_id"):
        return {}

    req = FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType(intent),
        orderList=[
            FinancialOrderOpenApiBaseSaveReqVO.model_validate(item)
            for item in (order_list or [])
        ],
        optionRfq=(
            GoatsOptionRfqReqVO.model_validate(option_rfq)
            if option_rfq is not None
            else None
        ),
        **_context(state),
    )
    result = await OptionClientHttpx().operate(req)
    return {
        "api_code": result.code,
        "api_result": result.data if result.code == 0 else result.msg,
    }
