"""Option 子图后端调用。"""
from __future__ import annotations

from typing import Any

from app.graph.state import AgentState
from app.subgraphs.option.sanitize import sanitize_order_list
from app.tools.option_client import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    GoatsOptionRfqReqVO,
    OptionClientHttpx,
    OptionIntentionType,
)

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
        "operatorUserId": state.get("operator_user_id"),
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
    result = await OptionClientHttpx().operate(req)
    return {
        "api_code": result.code,
        "api_result": result.data if result.code == 0 else result.msg,
    }
