"""`/admin-api/swap-order/*` 路由（对应 `SwapOrderOpenApiController.java`）。

按 `SwapIntentionType` 7 个枚举值分发业务行为，返回真实风格字符串。
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from mock_api.backend.fixtures import (
    COUNTERPARTIES,
    SECURITIES_DICT,
    now,
    order_seq,
    today,
)
from mock_api.backend.schemas import (
    SwapConversationOrderReqVO,
    SwapIntentionType,
    SwapOperateReqVO,
    SwapOrderItem,
    common_ok,
)

router = APIRouter(prefix="/admin-api/swap-order", tags=["mock-backend-swap"])


# ============================================================
# 内部工具
# ============================================================


def _resolve_stock_name(wind_code: str | None) -> str:
    """按 windCode 查标的简称，找不到回 windCode 自身。"""
    if not wind_code:
        return ""
    for item in SECURITIES_DICT:
        if item["windCode"].upper() == wind_code.upper():
            return item["insShtDesc"]
    return wind_code


def _direction_zh(d: str | None) -> str:
    return {
        "BUY": "买入",
        "SELL": "卖出",
        "SHORT_OPEN": "卖空",
        "SHORT_CLOSE": "平空",
    }.get(d or "", d or "")


def _price_type_zh(p: str | None) -> str:
    return {"LimitOrder": "限价委托", "MarketOrder": "市价委托"}.get(p or "", p or "")


def _format_order_brief(item: SwapOrderItem) -> str:
    """把单条 orderList 元素渲染成"互换订单卡片"中的一段文本。"""
    code = item.placeOrderWindCode or "(待补充)"
    name = _resolve_stock_name(code)
    direction = _direction_zh(item.placeOrderOrderDirection.value if item.placeOrderOrderDirection else None)
    qty = item.placeOrderQuantity or item.placeOrderQuantityHand or "(待补充)"
    qty_unit = "手" if item.placeOrderQuantityHand and not item.placeOrderQuantity else "股"
    price_type = _price_type_zh(item.placeOrderPriceType.value if item.placeOrderPriceType else None)
    price = item.placeOrderPrice
    algo = item.placeOrderAlgorithmType.value if item.placeOrderAlgorithmType else "(无)"
    short = item.placeOrderShortname or "(待选)"
    extra = f"  限价: {price}\n" if price is not None else ""
    return (
        f"  标的: {name}({code})\n"
        f"  方向: {direction or '(待补充)'}  数量: {qty}{qty_unit}\n"
        f"  价格类型: {price_type or '(待补充)'}\n"
        f"{extra}"
        f"  算法: {algo}\n"
        f"  交易对手: {short}\n"
    )


def _has_any_order_id(req: SwapOperateReqVO) -> bool:
    return any(o.orderId for o in req.orderList)


# ============================================================
# 按 type 分发的渲染函数
# ============================================================


def _render_place_or_modify(req: SwapOperateReqVO) -> str:
    """type=place_order_request：下单/改单 — 共用 type，靠 orderId 是否存在区分。"""
    is_modify = _has_any_order_id(req)
    title = "改单确认" if is_modify else "下单确认"
    new_order_id = order_seq.next("H")
    summary = (
        f"-----互换{title}-----\n"
        f"消息ID: {req.messageId}\n"
        f"会话ID: {req.conversationId or '(未传)'}\n"
        f"原话: {req.rawContent}\n\n"
        f"## 订单参数（{len(req.orderList)} 笔）\n"
    )
    for i, o in enumerate(req.orderList, 1):
        ref = f"  原单号: {o.orderId}\n" if o.orderId else f"  新单号: {new_order_id}\n"
        summary += f"\n[{i}]\n{ref}{_format_order_brief(o)}"
    summary += (
        f"\n如确认{('修改' if is_modify else '下单')}，请引用本消息回复"
        f"【确认{('改单' if is_modify else '下单')}】。"
    )
    return summary


def _render_confirm(req: SwapOperateReqVO, action: str) -> str:
    """type=confirm_order / confirm_cancel_order / confirm_modify_order — 已 commit 业务系统。"""
    refs = [o.orderId for o in req.orderList if o.orderId] or [order_seq.next("H")]
    return (
        f"-----互换{action}已受理-----\n"
        f"订单号: {', '.join(refs)}\n"
        f"提交时间: {now()}\n"
        f"提示: 已交易员审核，预计 5 分钟内完成处理。"
    )


def _render_cancel(req: SwapOperateReqVO) -> str:
    """type=cancel_order_request：发起撤单（未确认前）。"""
    refs = [o.orderId for o in req.orderList if o.orderId] or ["(待补充)"]
    return (
        f"-----互换撤单请求-----\n"
        f"待撤订单: {', '.join(refs)}\n"
        f"如确认撤单，请引用本消息回复【确认撤单】。"
    )


def _render_query(req: SwapOperateReqVO) -> str:
    """type=query_order_status：订单状态查询（mock 返回静态成交）。"""
    refs = [o.orderId for o in req.orderList if o.orderId] or ["H-20260510-00000001"]
    lines = [f"-----互换订单状态查询-----"]
    for r in refs:
        lines.append(
            f"\n订单号: {r}\n"
            f"  状态: 部分成交 (PARTIALLY_FILLED)\n"
            f"  已成交: 800 / 1000 股\n"
            f"  成交均价: 18.62\n"
            f"  成交金额: 14,896.00 HKD"
        )
    return "\n".join(lines)


def _render_unknown(req: SwapOperateReqVO) -> str:
    return (
        "未识别您的指令意图，请重新表达。\n"
        "支持的操作：下单 / 撤单 / 改单 / 确认下单 / 确认撤单 / 确认改单 / 查询订单状态。"
    )


_DISPATCH: dict[SwapIntentionType, Any] = {
    SwapIntentionType.PLACE_ORDER_REQUEST: _render_place_or_modify,
    SwapIntentionType.CONFIRM_ORDER: lambda r: _render_confirm(r, "确认下单"),
    SwapIntentionType.CONFIRM_CANCEL_ORDER: lambda r: _render_confirm(r, "确认撤单"),
    SwapIntentionType.CONFIRM_MODIFY_ORDER: lambda r: _render_confirm(r, "确认改单"),
    SwapIntentionType.CANCEL_ORDER_REQUEST: _render_cancel,
    SwapIntentionType.QUERY_ORDER_STATUS: _render_query,
    SwapIntentionType.UNKNOWN_INTENT: _render_unknown,
}


# ============================================================
# 路由
# ============================================================


@router.post("/operate")
async def swap_operate(req: SwapOperateReqVO) -> dict[str, Any]:
    """互换操作聚合接口（POST /admin-api/swap-order/operate）。

    按 `type` 分发到 7 个业务渲染函数，返回 Java `CommonResult<String>`。
    """
    handler = _DISPATCH.get(req.type)
    if handler is None:  # 防御：枚举校验已挡住非法值，这里兜底
        raise HTTPException(status_code=400, detail=f"unsupported type: {req.type}")
    return common_ok(handler(req))


@router.get("/get")
async def swap_order_get(orderId: str = Query(..., min_length=1)) -> dict[str, Any]:
    """互换订单详情（GET /admin-api/swap-order/get?orderId=）。

    对齐 `GoatsSwapOrderDO` 常用字段。
    """
    return common_ok({
        "orderId": orderId,
        "ultraContractCode": f"CSC-MOCK-{orderId}",
        "windCode": "0700.HK",
        "insShtDesc": "腾讯控股",
        "transactionType": "HK_STOCK",
        "orderDirection": "BUY",
        "priceType": "LimitOrder",
        "price": Decimal("472.00"),
        "quantity": 1000,
        "filledQty": 800,
        "avgPrice": Decimal("471.62"),
        "execAmount": Decimal("377296.00"),
        "currency": "HKD",
        "orderStatus": "PARTIALLY_FILLED",
        "ctptyShortName": COUNTERPARTIES[0]["shortName"],
        "createdDateTime": now(),
        "updatedDateTime": now(),
    })


@router.post("/get-conversation-orders")
async def swap_get_conversation_orders(
    req: SwapConversationOrderReqVO = Body(...),
) -> dict[str, Any]:
    """会话历史订单（POST /admin-api/swap-order/get-conversation-orders）。"""
    return common_ok([
        {
            "orderId": "H-" + today().replace("-", "") + "-00000001",
            "conversationId": req.conversationId,
            "windCode": "0700.HK",
            "insShtDesc": "腾讯控股",
            "transactionType": "HK_STOCK",
            "quantity": 1000,
            "orderDirection": "BUY",
            "priceType": "LimitOrder",
            "price": "472.00",
            "orderStatus": "FILLED",
            "createdDateTime": now(),
        },
    ])
