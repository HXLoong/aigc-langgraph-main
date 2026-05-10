"""`/admin-api/financial-orders/*` 路由（对应 `FinancialOrdersOpenApiController.java`）。

按 `stockOptionIntentionType` 16 个枚举值分发业务行为。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter

from mock_api.backend.fixtures import (
    COUNTERPARTIES,
    POSITIONS,
    SECURITIES_DICT,
    now,
    order_seq,
    today,
)
from mock_api.backend.schemas import (
    CloseOrderItem,
    FinancialOperateReqVO,
    FinancialOrderItem,
    QueryCloseOrdersReqVO,
    StockOptionIntentionType,
    common_ok,
)

router = APIRouter(
    prefix="/admin-api/financial-orders", tags=["mock-backend-financial"]
)


# ============================================================
# 内部工具
# ============================================================


def _resolve_stock(item: FinancialOrderItem) -> tuple[str, str]:
    """从 stockCode / stockName / stockCodeList 解析 (代码, 简称)，缺失填默认。"""
    code = item.stockCode or ""
    name = item.stockName or ""
    if code:
        for s in SECURITIES_DICT:
            if s["windCode"].upper() == code.upper():
                return s["windCode"], s["insShtDesc"]
    if not code and item.stockCodeList:
        for kw in item.stockCodeList:
            for s in SECURITIES_DICT:
                if (
                    kw.keyword.upper() == s["windCode"].upper()
                    or kw.keyword in s["insShtDesc"]
                ):
                    return s["windCode"], s["insShtDesc"]
    return code or "600519.SH", name or "贵州茅台"


def _format_inquiry(req: FinancialOperateReqVO) -> str:
    """new_inquiry：渲染询价卡。"""
    item = req.orderList[0] if req.orderList else FinancialOrderItem()
    code, name = _resolve_stock(item)
    opt_type = item.optionType or "欧式看涨"
    tenor = item.tenor or "1M"
    strike = (
        f"{item.strikePercentage}%"
        if item.strikePercentage is not None
        else "100%"
    )
    inquiry_id = order_seq.next("Q")
    counterparty_lines = "  ".join(
        f"{chr(65 + i)}.{cp['shortName']}" for i, cp in enumerate(COUNTERPARTIES)
    )
    return (
        f"-----场外期权询价详情-----\n"
        f"询价单号: {inquiry_id}\n"
        f"标的代码: {code}\n"
        f"标的名称: {name}\n"
        f"期权类型: {opt_type}\n"
        f"期限: {tenor}\n"
        f"执行价格: {strike}\n"
        f"期权费率: 6.88%（mock 示例）\n"
        f"名义本金: 待补充\n"
        f"建仓指令: 待补充\n"
        f"交易对手: 待补充\n\n"
        f"如需下单，请引用本消息补充【交易对手】【名义本金】【建仓指令】。\n"
        f"本群可选交易对手列表：{counterparty_lines}"
    )


def _format_place_or_modify(req: FinancialOperateReqVO, action: str) -> str:
    """place_order_from_quote / request_modify_order：下单或改单确认卡。"""
    items = req.orderList or [FinancialOrderItem()]
    order_id = order_seq.next("OPT")
    lines = [f"-----场外期权{action}-----", f"单号: {order_id}"]
    for i, item in enumerate(items, 1):
        code, name = _resolve_stock(item)
        notional = item.notionalAmount or Decimal("2000000")
        instruction = item.initialOrderInstruction or item.orderType or "市价下单"
        ctpty = item.shortName or "(待选)"
        lines.append(
            f"\n[{i}]\n"
            f"  标的: {name}({code})\n"
            f"  期权类型: {item.optionType or '欧式看涨'} 期限 {item.tenor or '1M'}\n"
            f"  执行价: {item.strikePercentage or 100}%\n"
            f"  名义本金: {notional:,}\n"
            f"  建仓指令: {instruction}\n"
            f"  交易对手: {ctpty}"
        )
    lines.append(f"\n如确认{action}，请引用本消息回复【确认下单】以提交审核。")
    return "\n".join(lines)


def _format_confirm(action: str) -> str:
    """confirm_order / confirm_cancel_order / confirm_modify_order：终态确认。"""
    return (
        f"-----场外期权{action}已受理-----\n"
        f"提交时间: {now()}\n"
        f"提示: 请等待业务后台处理，预计 1-3 分钟内完成。"
    )


def _format_cancel(req: FinancialOperateReqVO) -> str:
    """cancel_order_request / request_cancel_order：撤单请求。"""
    refs = [o.orderId for o in (req.orderList or []) if o.orderId] or ["(待补充)"]
    return (
        f"-----场外期权撤单请求-----\n"
        f"待撤订单: {', '.join(refs)}\n"
        f"如确认撤单，请引用本消息回复【确认撤单】。"
    )


def _format_query_status(req: FinancialOperateReqVO) -> str:
    """query_order_status：订单状态查询。"""
    refs = [o.orderId for o in (req.orderList or []) if o.orderId] or [
        "OPT-" + today().replace("-", "") + "-00000001"
    ]
    lines = ["-----场外期权订单状态-----"]
    for r in refs:
        lines.append(
            f"\n订单号: {r}\n"
            f"  状态: 已成交 (FILLED)\n"
            f"  名义本金: 2,000,000\n"
            f"  期权费: 137,600\n"
            f"  币种: CNY"
        )
    return "\n".join(lines)


def _format_close_holdings(req: FinancialOperateReqVO) -> str:
    """close_order_query：可平仓持仓列表。"""
    blocks = []
    for i, p in enumerate(POSITIONS, 1):
        avail = "是" if p["availableNotional"] > 0 else "否"
        blocks.append(
            f"-----场外期权持仓详情-----\n"
            f"序号: {i}\n"
            f"单号: {p['orderId']}\n"
            f"合约编号: {p['contractCode']}\n"
            f"期权类型: {p['optionType']}\n"
            f"标的信息: {p['underlyingCode']} {p['underlyingName']}\n"
            f"当日剩余可申请平仓名义本金: {p['availableNotional']:,}\n"
            f"合约剩余名义本金: {p['notional']:,}\n"
            f"是否可平仓: {avail}"
        )
    blocks.append(
        "如需平仓，请引用本消息回复【持仓序号或合约编号】【平仓名义本金】【平仓价格方式】。\n"
        "例如：序号1，200w，市价下单"
    )
    return "\n\n".join(blocks)


def _format_close_place(req: FinancialOperateReqVO) -> str:
    """close_order_request：平仓申请确认卡。"""
    items: list[CloseOrderItem] = (
        req.closeOrderReqVO.closeOrderList if req.closeOrderReqVO and req.closeOrderReqVO.closeOrderList else []
    )
    if not items:
        items = [CloseOrderItem(contractCode=POSITIONS[0]["contractCode"], closeNotionalAmount=Decimal("2000000"))]

    close_id = order_seq.next("CO")
    lines = ["-----场外期权平仓申请-----", f"平仓单号: {close_id}"]
    for i, it in enumerate(items, 1):
        contract = it.contractCode or "(待补充)"
        notional = it.closeNotionalAmount or Decimal("2000000")
        order_type = it.orderType or "MARKET_PRICE"
        price = f"，限价 {it.limitPrice}" if it.limitPrice is not None else ""
        # 关联持仓
        underlying = next(
            (p for p in POSITIONS if p["contractCode"] == contract),
            POSITIONS[0],
        )
        lines.append(
            f"\n[{i}]\n"
            f"  合约编号: {contract}\n"
            f"  标的信息: {underlying['underlyingCode']} {underlying['underlyingName']}\n"
            f"  平仓名义本金: {notional:,}\n"
            f"  建仓方式: {order_type}{price}"
        )
    lines.append("\n如确认平仓，请引用本消息回复【确认平仓】。")
    return "\n".join(lines)


def _format_close_cancel(req: FinancialOperateReqVO) -> str:
    """close_order_cancel_request：平仓订单撤单请求。"""
    cancel_list = (
        req.closeOrderReqVO.cancelOrderNoList
        if req.closeOrderReqVO and req.closeOrderReqVO.cancelOrderNoList
        else ["(待补充)"]
    )
    return (
        f"-----场外期权平仓撤单请求-----\n"
        f"待撤平仓单: {', '.join(cancel_list)}\n"
        f"如确认撤单，请引用本消息回复【确认撤单】。"
    )


def _format_close_query(req: FinancialOperateReqVO) -> str:
    """close_order_order_query：平仓订单查询。"""
    trade_date = (
        req.closeOrderReqVO.tradeDate
        if req.closeOrderReqVO and req.closeOrderReqVO.tradeDate
        else today()
    )
    return (
        f"-----场外期权平仓订单查询-----\n"
        f"交易日期: {trade_date}\n"
        f"\n[1]\n"
        f"  平仓单号: CO-{trade_date.replace('-', '')}-A1B2C3D4\n"
        f"  合约编号: {POSITIONS[0]['contractCode']}\n"
        f"  状态: 已成交\n"
        f"  名义本金: 2,000,000\n"
        f"  成交价: 0.205"
    )


def _format_unknown(req: FinancialOperateReqVO) -> str:
    return (
        "未识别您的指令意图，请重新表达。\n"
        "支持的操作：询价 / 下单 / 撤单 / 改单 / 查询订单 / 平仓查询 / 平仓下单 / 平仓撤单 等。"
    )


_DISPATCH: dict[StockOptionIntentionType, Any] = {
    StockOptionIntentionType.NEW_INQUIRY: _format_inquiry,
    StockOptionIntentionType.PLACE_ORDER_FROM_QUOTE: lambda r: _format_place_or_modify(r, "下单确认"),
    StockOptionIntentionType.REQUEST_MODIFY_ORDER: lambda r: _format_place_or_modify(r, "改单确认"),
    StockOptionIntentionType.CONFIRM_ORDER: lambda r: _format_confirm("确认下单"),
    StockOptionIntentionType.CONFIRM_CANCEL_ORDER: lambda r: _format_confirm("确认撤单"),
    StockOptionIntentionType.CONFIRM_MODIFY_ORDER: lambda r: _format_confirm("确认改单"),
    StockOptionIntentionType.CANCEL_ORDER_REQUEST: _format_cancel,
    StockOptionIntentionType.REQUEST_CANCEL_ORDER: _format_cancel,
    StockOptionIntentionType.QUERY_ORDER_STATUS: _format_query_status,
    StockOptionIntentionType.CLOSE_ORDER_QUERY: _format_close_holdings,
    StockOptionIntentionType.CLOSE_ORDER_REQUEST: _format_close_place,
    StockOptionIntentionType.CLOSE_ORDER_CONFIRM: lambda r: _format_confirm("平仓确认下单"),
    StockOptionIntentionType.CLOSE_ORDER_CANCEL_REQUEST: _format_close_cancel,
    StockOptionIntentionType.CLOSE_ORDER_CANCEL_CONFIRM: lambda r: _format_confirm("平仓确认撤单"),
    StockOptionIntentionType.CLOSE_ORDER_ORDER_QUERY: _format_close_query,
    StockOptionIntentionType.UNKNOWN_INTENT: _format_unknown,
}


# ============================================================
# 路由
# ============================================================


@router.post("/operate")
async def financial_operate(req: FinancialOperateReqVO) -> dict[str, Any]:
    """期权 / 平仓操作聚合接口（POST /admin-api/financial-orders/operate）。"""
    handler = _DISPATCH.get(req.type)
    if handler is None:
        return common_ok(_format_unknown(req))
    return common_ok(handler(req))


@router.post("/query-close-orders")
async def query_close_orders(
    req: QueryCloseOrdersReqVO,
) -> dict[str, Any]:
    """批量查询平仓订单/合约（POST /admin-api/financial-orders/query-close-orders）。

    对齐 `CloseOrderInfoRespVO`：返回 `[{orderId, availableNotional, notional, contractCode}]`。
    """
    order_ids = set(req.orderIds or [])
    contract_codes = set(req.contractCodes or [])
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in POSITIONS:
        match = (
            (p["orderId"] in order_ids) or (p["contractCode"] in contract_codes)
        )
        if not order_ids and not contract_codes:
            match = True  # 都不传时返回全部
        if match and p["orderId"] not in seen:
            seen.add(p["orderId"])
            result.append(
                {
                    "orderId": p["orderId"],
                    "availableNotional": p["availableNotional"],
                    "notional": p["notional"],
                    "contractCode": p["contractCode"],
                }
            )
    return common_ok(result)
