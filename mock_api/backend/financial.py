"""期权 / 平仓 mock wire 契约；进程内模拟状态不代表真实成交。

操作状态按房间、用户、会话隔离，最多保留 1024 个最近使用的会话。
query-close-orders 的 Java DTO 没有会话字段，动态单号查询按 roomId 限定。
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request

from mock_api.backend.fixtures import COUNTERPARTIES, POSITIONS, SECURITIES_DICT, order_seq
from mock_api.backend.schemas import (
    CloseOrderItem,
    FinancialOperateReqVO,
    FinancialOrderItem,
    QueryCloseOrdersReqVO,
    StockOptionIntentionType,
    common_ok,
)

router = APIRouter(prefix="/admin-api/financial-orders", tags=["mock-backend-financial"])
_MISSING = "【待补充】"
_NOTE = "（mock 模拟回执，不代表真实交易）"


@dataclass
class _Order:
    item: FinancialOrderItem | CloseOrderItem
    status: str = "待补充参数"
    position: dict[str, Any] | None = None


_Orders = dict[str, _Order]
_Scopes = OrderedDict[tuple[str, str, str], _Orders]


def _scopes(request: Request) -> _Scopes:
    if not hasattr(request.app.state, "financial_orders"):
        request.app.state.financial_orders = OrderedDict()
    return request.app.state.financial_orders


def _orders(request: Request, req: FinancialOperateReqVO) -> _Orders:
    scopes = _scopes(request)
    key = (req.roomId, req.userId, req.conversationId or "")
    orders = scopes.setdefault(key, {})
    scopes.move_to_end(key)
    while len(scopes) > 1024:
        scopes.popitem(last=False)
    return orders


def _next_id(prefix: str) -> str:
    value = order_seq.next(prefix)
    if prefix == "Q":
        stem, number = value.rsplit("-", 1)
        return f"{stem}-{number.zfill(10)}"
    return value


def _resolve_stock(item: FinancialOrderItem) -> tuple[str, str]:
    code, name = item.stockCode or "", item.stockName or ""
    expressions = [code, name, *(keyword.keyword for keyword in item.stockCodeList or [])]
    exact = [stock for stock in SECURITIES_DICT if any(
        text and (text.upper() == stock["windCode"].upper() or text == stock["insShtDesc"])
        for text in expressions
    )]
    matches = exact or [stock for stock in SECURITIES_DICT if any(
        text and text in stock["insShtDesc"] for text in expressions
    )]
    if len(matches) == 1:
        return matches[0]["windCode"], matches[0]["insShtDesc"]
    return code or _MISSING, name or _MISSING


def _amount(value: Decimal | None) -> str:
    return f"{value:,}" if value is not None else _MISSING


def _complete(item: FinancialOrderItem | CloseOrderItem) -> bool:
    if isinstance(item, FinancialOrderItem):
        code, name = _resolve_stock(item)
        return bool(
            code != _MISSING
            and name != _MISSING
            and item.notionalAmount is not None
            and item.notionalAmount > 0
            and (item.orderType or item.initialOrderInstruction)
            and item.shortName
        )
    return bool(
        item.closeOrderNotionalDelta is not None
        and item.closeOrderNotionalDelta > 0
        and item.closeOrderType in {"限价单", "市价单", "POV", "TWAP"}
        and (item.closeOrderType != "限价单" or item.closeOrderPrice is not None)
        and (
            item.closeOrderType != "TWAP"
            or (item.closeOrderAlgoStartTime and item.closeOrderAlgoEndTime)
        )
    )


def _option_card(order_id: str, order: _Order, seq: int) -> str:
    assert isinstance(order.item, FinancialOrderItem)
    item = order.item
    code, name = _resolve_stock(item)
    return (
        f"序号：{seq}\n单号：{order_id}\n"
        f"期权类型：{item.optionType or '欧式看涨'}\n"
        f"标的代码：{code}\n标的名称：{name}\n期限：{item.tenor or _MISSING}\n"
        f"执行价格：{item.strikePercentage if item.strikePercentage is not None else _MISSING}%\n"
        f"名义本金：{_amount(item.notionalAmount)}\n"
        f"建仓指令：{item.initialOrderInstruction or item.orderType or _MISSING}\n"
        f"交易对手：{item.shortName or _MISSING}\n状态：{order.status}"
    )


def _close_card(order_id: str, order: _Order, seq: int) -> str:
    assert isinstance(order.item, CloseOrderItem)
    item = order.item
    position = order.position or {}
    extras = []
    for label, value in (
        ("限定价格", item.closeOrderPrice),
        ("POV比例", item.closeOrderPovRatio),
        ("TWAP开始时间", item.closeOrderAlgoStartTime),
        ("TWAP结束时间", item.closeOrderAlgoEndTime),
    ):
        if value is not None:
            extras.append(f"{label}：{value}")
    return (
        f"序号：{seq}\n单号：{order_id}\n合约编号：{item.internalTradeId}\n"
        f"标的信息：{position.get('underlyingCode', '')} {position.get('underlyingName', '')}\n"
        f"平仓名义本金：{_amount(item.closeOrderNotionalDelta)}\n"
        f"平仓价格方式：{item.closeOrderType or _MISSING}\n"
        + "\n".join(extras)
        + f"\n状态：{order.status}"
        + (f"\n参数需要完善：{_MISSING}" if not _complete(item) else "")
    )


def _option_request(req: FinancialOperateReqVO, orders: _Orders) -> str:
    inquiry = req.type == StockOptionIntentionType.NEW_INQUIRY
    title = (
        "询价详情"
        if inquiry
        else (
            "改单确认" if req.type == StockOptionIntentionType.REQUEST_MODIFY_ORDER else "下单确认"
        )
    )
    lines = [f"-----场外期权{title}-----"]
    for seq, item in enumerate(req.orderList, 1):
        if item.orderId:
            order = orders.get(item.orderId)
            if order is None or not isinstance(order.item, FinancialOrderItem):
                lines.append(f"期权订单{item.orderId}：订单不存在")
                continue
            if order.status not in {"待补充参数", "待确认"}:
                lines.append(f"期权订单{item.orderId}：当前状态不允许修改")
                continue
            merged = {**order.item.model_dump(), **item.model_dump(exclude_none=True)}
            order.item = FinancialOrderItem.model_validate(merged)
        else:
            item = item.model_copy(update={"orderId": _next_id("Q")})
            order = _Order(item)
            orders[item.orderId] = order
        order.status = "待确认" if _complete(order.item) else "待补充参数"
        lines.append(_option_card(item.orderId, order, seq))
    if not req.orderList:
        lines.append("请提供询价或订单参数。")
    elif any(_MISSING in line for line in lines):
        lines.append("如需下单，请引用本消息补充【交易对手】【名义本金】【建仓指令】。")
        lines.extend(f"{chr(65 + i)}. {cp['shortName']}" for i, cp in enumerate(COUNTERPARTIES))
    else:
        lines.append("如订单无误，请引用本消息回复【确认下单】。")
    return "\n\n".join(lines)


def _seed_close(orders: _Orders, position: dict[str, Any]) -> _Order:
    return orders.setdefault(
        position["orderId"],
        _Order(
            CloseOrderItem(orderId=position["orderId"], internalTradeId=position["contractCode"]),
            position=dict(position),
        ),
    )


def _close_holdings(req: FinancialOperateReqVO, orders: _Orders) -> str:
    lines = ["-----场外期权持仓详情-----"]
    for seq, position in enumerate(POSITIONS, 1):
        _seed_close(orders, position)
        lines.append(
            f"序号：{seq}\n单号：{position['orderId']}\n合约编号：{position['contractCode']}\n"
            f"期权类型：{position['optionType']}\n"
            f"标的信息：{position['underlyingCode']} {position['underlyingName']}\n"
            f"当日剩余可申请平仓名义本金：{position['availableNotional']:,}\n"
            f"合约剩余名义本金：{position['notional']:,}"
        )
    lines.append("如需平仓，请引用本消息补充持仓序号、平仓名义本金及平仓价格方式。")
    return "\n\n".join(lines)


def _close_request(req: FinancialOperateReqVO, orders: _Orders) -> str:
    lines = ["-----场外期权平仓申请-----", "以下平仓申请，请核对详情后确认"]
    items = req.closeOrderReqVO.closeOrderList if req.closeOrderReqVO else None
    for seq, item in enumerate(items or [], 1):
        if item.orderId:
            order = orders.get(item.orderId)
            if order is None:
                position = next((p for p in POSITIONS if p["orderId"] == item.orderId), None)
                order = _seed_close(orders, position) if position else None
            if order is None or not isinstance(order.item, CloseOrderItem):
                lines.append(f"订单{item.orderId}：订单不存在")
                continue
            if item.internalTradeId and item.internalTradeId != order.item.internalTradeId:
                lines.append(f"订单{item.orderId}：合约编号与订单不匹配")
                continue
            if order.status not in {"待补充参数", "待确认"}:
                lines.append(f"订单{item.orderId}：当前状态不允许修改")
                continue
            merged = {**order.item.model_dump(), **item.model_dump(exclude_none=True)}
            order.item = CloseOrderItem.model_validate(merged)
        else:
            position = next(
                (p for p in POSITIONS if p["contractCode"] == item.internalTradeId), None
            )
            if position is None:
                lines.append(f"合约编号不存在：{item.internalTradeId or _MISSING}")
                continue
            item = item.model_copy(update={"orderId": _next_id("CO")})
            order = _Order(item, position=dict(position))
            orders[item.orderId] = order
        order.status = "待确认" if _complete(order.item) else "待补充参数"
        lines.append(_close_card(item.orderId, order, seq))
    if not items:
        lines.append("请提供平仓订单号或合约编号。")
    lines.append("如参数完整，请引用本消息回复【确认平仓】。")
    return "\n\n".join(lines)


def _references(req: FinancialOperateReqVO) -> list[str]:
    close = req.closeOrderReqVO
    field = {
        StockOptionIntentionType.CLOSE_ORDER_CONFIRM: "confirmOrderNoList",
        StockOptionIntentionType.CLOSE_ORDER_CANCEL_REQUEST: "cancelOrderNoList",
        StockOptionIntentionType.CLOSE_ORDER_CANCEL_CONFIRM: "confirmCancelOrderNoList",
        StockOptionIntentionType.CLOSE_ORDER_ORDER_QUERY: "queryOrderNoList",
    }.get(req.type)
    if field:
        return list(dict.fromkeys(getattr(close, field) or [])) if close else []
    return list(dict.fromkeys(item.orderId for item in req.orderList if item.orderId))


def _transition(req: FinancialOperateReqVO, orders: _Orders) -> str:
    is_close = req.type.value.startswith("close_")
    product = "期权平仓订单" if is_close else "期权订单"
    query = req.type in {
        StockOptionIntentionType.QUERY_ORDER_STATUS,
        StockOptionIntentionType.CLOSE_ORDER_ORDER_QUERY,
    }
    cancel_request = req.type in {
        StockOptionIntentionType.CANCEL_ORDER_REQUEST,
        StockOptionIntentionType.REQUEST_CANCEL_ORDER,
        StockOptionIntentionType.CLOSE_ORDER_CANCEL_REQUEST,
    }
    cancel_confirm = req.type in {
        StockOptionIntentionType.CONFIRM_CANCEL_ORDER,
        StockOptionIntentionType.CLOSE_ORDER_CANCEL_CONFIRM,
    }
    action = (
        "订单状态"
        if query
        else (
            "撤单请求"
            if cancel_request
            else "确认撤单"
            if cancel_confirm
            else "确认改单"
            if req.type == StockOptionIntentionType.CONFIRM_MODIFY_ORDER
            else "确认下单"
        )
    )
    lines = [f"-----场外期权{'平仓' if is_close else ''}{action}-----"]
    if is_close and query:
        lines[0] = "-----场外期权平仓订单查询-----"
    refs = _references(req)
    if not refs and query:
        refs = [key for key in orders if key.startswith("CO-" if is_close else "Q-")]
    for seq, order_id in enumerate(refs, 1):
        order = orders.get(order_id)
        if order is None or isinstance(order.item, CloseOrderItem) != is_close:
            lines.append(f"{product}{order_id}：订单不存在")
            continue
        detail = f"序号：{seq}\n单号：{order_id}"
        if order.position:
            detail += f"\n合约编号：{order.position['contractCode']}"
        if query:
            lines.append(detail + f"\n状态：{order.status}")
            continue
        allowed = (
            {"待撤单确认"}
            if cancel_confirm
            else ({"已提交", "待撤单确认"} if cancel_request else {"待确认"})
        )
        if order.status not in allowed:
            reason = "参数需要完善" if not _complete(order.item) else "当前状态不允许此操作"
            lines.append(detail + f"\n{product}{order_id}：{reason}")
            continue
        if cancel_request:
            order.status = "待撤单确认"
            message = "已收到您的撤单请求，请引用本消息回复【确认撤单】。"
        elif cancel_confirm:
            order.status = "已撤单"
            message = "已收到您的撤单请求。模拟状态：已撤单。"
        else:
            order.status = "已提交"
            message = "已收到您的下单请求，待交易员审核。"
        lines.append(detail + f"\n{product}{order_id}：{message}")
    if not refs:
        lines.append("暂无订单，请提供订单号。")
    return "\n\n".join(lines)


@router.post("/operate")
async def financial_operate(req: FinancialOperateReqVO, request: Request) -> dict[str, Any]:
    orders = _orders(request, req)
    if req.type == StockOptionIntentionType.NEW_INQUIRY:
        for item in req.orderList:
            if item.stockCode and _resolve_stock(item)[1] == _MISSING:
                return {
                    "code": 400,
                    "data": None,
                    "msg": f"标的代码（或标的名称）{item.stockCode} 不在标的池内，无法自动报价。",
                }
    if req.type in {
        StockOptionIntentionType.NEW_INQUIRY,
        StockOptionIntentionType.PLACE_ORDER_FROM_QUOTE,
        StockOptionIntentionType.REQUEST_MODIFY_ORDER,
    }:
        result = _option_request(req, orders)
    elif req.type == StockOptionIntentionType.CLOSE_ORDER_QUERY:
        result = _close_holdings(req, orders)
    elif req.type == StockOptionIntentionType.CLOSE_ORDER_REQUEST:
        result = _close_request(req, orders)
    elif req.type == StockOptionIntentionType.UNKNOWN_INTENT:
        result = "未识别您的指令意图，请重新表达。"
    else:
        result = _transition(req, orders)
    return common_ok(result + "\n" + _NOTE)


@router.post("/query-close-orders")
async def query_close_orders(req: QueryCloseOrdersReqVO, request: Request) -> dict[str, Any]:
    """返回真实 CloseOrderInfoRespVO 四字段，不把平仓申请金额当成持仓余额。"""
    rows = {position["orderId"]: position for position in POSITIONS}
    if req.roomId:
        for (room, _user, _conversation), orders in _scopes(request).items():
            if room != req.roomId:
                continue
            for order_id, order in orders.items():
                if order.position:
                    rows[order_id] = {**order.position, "orderId": order_id}
    selected = [
        {
            field: row[field]
            for field in ("orderId", "contractCode", "availableNotional", "notional")
        }
        for row in rows.values()
        if row["orderId"] in (req.orderIds or [])
    ]
    # Java 分别查询订单和合约：合约信息不绑定任何已创建的 CO 订单。
    selected.extend(
        {
            "orderId": None,
            "contractCode": position["contractCode"],
            "availableNotional": position["availableNotional"],
            "notional": position["notional"],
        }
        for position in POSITIONS
        if position["contractCode"] in (req.contractCodes or [])
    )
    return common_ok(selected)
