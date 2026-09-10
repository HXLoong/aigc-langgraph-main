"""close 子图后端调用。

对齐 Dify `期权平仓`[code] 节点（spec/code_nodes/期权平仓.py）：POST
`/admin-api/financial-orders/operate`，payload 固定 `orderList: []` +
`closeOrderReqVO: {...}`（不像 option 子图那样把订单参数塞进 orderList）。

刻意不复用 `app.subgraphs.option.backend.call_option_backend`——旧实现把
close 的订单参数 (confirmOrderNoList / cancelOrderNoList / closeOrderList 等)
塞进了 `FinancialOrderOpenApiSaveReqVO.orderList`，与 Dify 平仓真实 payload
（`orderList` 恒为 `[]`，业务参数全部在 `closeOrderReqVO` 里）不一致（P0
payload 对齐项）。本模块独立维护 `_context`/`_message_id`，避免与 option 域
共享可变状态，两域各自独立演进。
"""
from __future__ import annotations

from typing import Any

from app.graph.state import AgentState
from app.subgraphs.close.aggregate import sanitize_close_order_req_vo
from app.tools.option_client import (
    CloseOrderReqVO,
    FinancialOrderOpenApiSaveReqVO,
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


async def call_close_backend(
    state: AgentState,
    *,
    intent: str,
    close_order_req_vo: dict[str, Any],
) -> dict[str, Any]:
    """调用真后端 `/admin-api/financial-orders/operate`（平仓语义）。

    Args:
        intent: close_order_* 之一（对齐 `OptionIntentionType`）。
        close_order_req_vo: `aggregate.build_close_order_req_vo` 的产出
            （未清洗）；本函数内部完成"前置清洗"再发送。

    Returns:
        `{}`（缺必要上下文时静默跳过，与 option 域 `call_option_backend`
        同款降级约定）或 `{"api_code": ..., "api_result": ...}`（`api_result`
        直接取后端返回的 `data`/`msg`，**不做本地二次加工**——CLAUDE.md P0：
        严禁掩盖后端真实响应）。
    """
    if not state.get("conversation_id") or not state.get("room_id") or not state.get("user_id"):
        return {}

    sanitized = sanitize_close_order_req_vo(close_order_req_vo)
    req = FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType(intent),
        orderList=[],
        closeOrderReqVO=CloseOrderReqVO.model_validate(sanitized),
        optionRfq=None,
        **_context(state),
    )
    result = await OptionClientHttpx().operate(req)
    return {
        "api_code": result.code,
        "api_result": result.data if result.code == 0 else result.msg,
    }


__all__ = ["call_close_backend"]
