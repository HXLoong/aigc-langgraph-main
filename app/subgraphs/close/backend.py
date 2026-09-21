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

from app.execution.operations import capture_operation
from app.extraction.identity import protect_identity_lists
from app.extraction.locks import protect_orders
from app.graph.state import AgentState
from app.subgraphs.close.aggregate import sanitize_close_order_req_vo
from app.tools.bot_context import BotContext, normalize_message_id
from app.tools.exceptions import MissingBackendContextError
from app.tools.option_client import (
    CloseOrderReqVO,
    FinancialOrderOpenApiSaveReqVO,
    OptionClientHttpx,
    OptionIntentionType,
)
from app.tools.receipts import receipt_guard, receipt_update


def _message_id(value: Any) -> int:
    return normalize_message_id(value)


def _context(state: AgentState) -> dict[str, Any]:
    """机器人上下文 → Java ReqVO 字段；唯一定义在 app/tools/bot_context.py。"""
    wire = BotContext.from_state(state).to_wire()
    return wire


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
        Java 原始业务码与回执；缺上下文或不可验证回执显式报错。
    """
    missing = BotContext.from_state(state).missing_required()
    if missing:
        raise MissingBackendContextError("close", missing)

    close_order_req_vo, identity_rejected = protect_identity_lists(state, close_order_req_vo)
    protected, rejected = protect_orders(
        state, close_order_req_vo.get("closeOrderList") or [], product="close",
    )
    rejected = {**rejected, **identity_rejected}
    sanitized = sanitize_close_order_req_vo({**close_order_req_vo, "closeOrderList": protected})
    req = FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType(intent),
        orderList=[],
        closeOrderReqVO=CloseOrderReqVO.model_validate(sanitized),
        optionRfq=None,
        **_context(state),
    )
    if capture_operation("close", req):
        return {"field_records": rejected} if rejected else {}
    async with receipt_guard("close"):
        result = await OptionClientHttpx().operate(req)
    return {
        **({"field_records": rejected} if rejected else {}),
        **receipt_update(result, "close"),
    }


__all__ = ["call_close_backend"]
