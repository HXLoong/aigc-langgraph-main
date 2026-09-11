"""Swap 子图后端调用（Issue #79，类比 option/backend.py）。

集成 swap_place_order / swap_confirm / swap_cancel / swap_query_order 4 个节点
到真后端 POST /admin-api/swap-order/operate。

行为：
- 校验并提取 state 的机器人上下文，缺失时显式报错
- 把 LLM 提取出的 orderList + ticker 解析结果合并
- 调 SwapClientHttpx().operate(req) → 返回 {api_code, api_result}
- code=0 取 data，code!=0 取 msg；空结果显式报错，非空结果不改写
- 后端异常由调用方 @safe_node 捕获，交给 render 输出系统失败提示

注：swap 的 4 个意图共用 SwapClient.operate endpoint，按 SwapIntentionType.type 区分。
"""
from __future__ import annotations

import logging
from typing import Any

from app.graph.state import AgentState
from app.subgraphs.swap.prewash import sanitize_order_list
from app.tools.exceptions import EmptyBackendResultError, MissingBackendContextError
from app.tools.swap_client import (
    SwapClientHttpx,
    SwapIntentionType,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
)

logger = logging.getLogger(__name__)


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
        # DSL v2「互换开仓」新增字段：操作者（替代旧 userId 语义，见
        # app/graph/state.py operator_user_id docstring）；state 未填时留空串，
        # SwapOrderOpenApiSaveReqVO 是 extra="allow"，透传给后端即可。
        "operatorUserId": state.get("operator_user_id", "") or "",
    }


def _is_empty_backend_result(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list, tuple, set)):
        return not value
    return False


def _with_resolved_ticker(
    order: dict[str, Any], tickers: list[Any], index: int
) -> dict[str, Any]:
    """把 ticker resolver 的 windCode 写回 orderList[i].placeOrderWindCode。

    swap 用 placeOrderWindCode（与 option 的 stockCode 字段名不同）。
    """
    if index < len(tickers):
        ticker = tickers[index]
        wind_code = getattr(ticker, 'wind_code', None)
        if wind_code is None and isinstance(ticker, dict):
            wind_code = ticker.get("windCode")
        if wind_code:
            order["placeOrderWindCode"] = wind_code
    return order


async def call_swap_backend(
    state: AgentState,
    *,
    intent: str,
    order_list: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """调真后端 POST /admin-api/swap-order/operate。

    Args:
        state: 当前节点 state（提供机器人上下文 + raw_text）
        intent: SwapIntentionType 枚举值（如 'place_order_request' / 'confirm_order'）
        order_list: LLM 提取的订单列表（已用 ticker 解析填好 windCode）

    Returns:
        partial state update：{"api_code": int, "api_result": ...}

    Raises:
        MissingBackendContextError: 缺少调用后端必需的机器人上下文字段。
    """
    missing_fields = [
        field
        for field in ("conversation_id", "room_id", "user_id")
        if not state.get(field)
    ]
    if _message_id(state.get("message_id")) <= 0:
        missing_fields.append("message_id")
    if missing_fields:
        logger.error(
            "swap backend call blocked: missing_fields=%s",
            ",".join(missing_fields),
        )
        raise MissingBackendContextError("swap", missing_fields)

    # 互换开仓-前置清洗（DSL v2）：字面量 "null" 字符串 → None，list 中的 None
    # 元素丢弃；只清洗 orderList，顶层 type 不清洗（见 prewash.py docstring）。
    cleaned_order_list = sanitize_order_list(order_list)

    req = SwapOrderOpenApiSaveReqVO(
        type=SwapIntentionType(intent),
        orderList=[
            SwapOrderOpenApiBaseSaveReqVO.model_validate(item)
            for item in cleaned_order_list
        ],
        **_context(state),
    )
    result = await SwapClientHttpx().operate(req)
    backend_result = result.data if result.code == 0 else result.msg
    if _is_empty_backend_result(backend_result):
        raise EmptyBackendResultError("swap", result.code)
    return {
        "api_code": result.code,
        "api_result": backend_result,
    }


__all__ = [
    "call_swap_backend",
    "_with_resolved_ticker",
    "_is_empty_backend_result",
    "_context",
    "_message_id",
]
