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
import re
from typing import Any

from app.execution.operations import capture_operation
from app.extraction.locks import protect_orders
from app.graph.state import AgentState, TickerCandidate
from app.subgraphs.swap.prewash import sanitize_order_list
from app.tools.bot_context import BotContext, normalize_message_id
from app.tools.exceptions import MissingBackendContextError
from app.tools.receipts import receipt_guard, receipt_update
from app.tools.swap_client import (
    SwapClientHttpx,
    SwapIntentionType,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
)

logger = logging.getLogger(__name__)


def _message_id(value: Any) -> int:
    return normalize_message_id(value)


def _context(state: AgentState) -> dict[str, Any]:
    """机器人上下文 → Java ReqVO 字段；唯一定义在 app/tools/bot_context.py。"""
    wire = BotContext.from_state(state).to_wire()
    # 互换 operate 未填操作者透传空串（ReqVO extra="allow"）
    wire["operatorUserId"] = wire["operatorUserId"] or ""
    return wire


def _is_empty_backend_result(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list, tuple, set)):
        return not value
    return False


def _with_resolved_ticker(
    order: dict[str, Any], tickers: list[Any]
) -> tuple[dict[str, Any], str]:
    """按订单标的身份绑定唯一的已验证证券，无法确定时保留原值。"""
    original_code = (order.get("placeOrderWindCode") or "").strip().upper()
    if not original_code:
        return order, "missing"

    verified: list[dict[str, Any]] = []
    for ticker in tickers:
        if isinstance(ticker, TickerCandidate):
            data = ticker.model_dump(by_alias=True)
        elif isinstance(ticker, dict):
            data = ticker
        else:
            continue
        wind_code = data.get("windCode")
        if (
            data.get("from_goats") is not True
            or not isinstance(wind_code, str)
            or not wind_code.strip()
        ):
            continue
        requested_market = order.get("placeOrderTransactionType")
        if requested_market and requested_market not in (data.get("transactionTypeLists") or []):
            continue
        verified.append(data)
        if wind_code.strip().upper() == original_code:
            order["placeOrderWindCode"] = wind_code
            return order, "matched_code"

    # 已带后缀的代码不得再按其他证券的别名解释，交后端校验。
    if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*\.[A-Z][A-Z0-9]*", original_code):
        return order, "unmatched"

    matches: dict[str, str] = {}
    for data in verified:
        wind_code = data["windCode"]
        aliases = [
            data.get("insShtDesc"), data.get("insLngDesc"),
            wind_code.strip().rsplit(".", 1)[0],
        ]
        aliases.extend(data.get("sourceKeywords") or [])
        if any(
            isinstance(alias, str) and alias.strip().upper() == original_code
            for alias in aliases
        ):
            matches[wind_code.strip().upper()] = wind_code
    if len(matches) == 1:
        order["placeOrderWindCode"] = next(iter(matches.values()))
        return order, "matched_alias"
    return order, "ambiguous" if matches else "unmatched"


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
    order_list, rejected = protect_orders(state, order_list or [], product="swap")
    missing_fields = BotContext.from_state(state).missing_required()
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
    if capture_operation("swap", req):
        return {"field_records": rejected} if rejected else {}
    async with receipt_guard("swap"):
        result = await SwapClientHttpx().operate(req)
    return {
        **({"field_records": rejected} if rejected else {}),
        **receipt_update(result, "swap"),
    }
