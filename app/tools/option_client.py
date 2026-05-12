"""OptionClient — POST /admin-api/financial-orders/operate（contracts §2）。

承担期权全 16 个意图（stockOptionIntentionType）：询价 / 下单 / 改单 / 撤单 / 平仓 / 查询 / 确认。
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.tools.models import (
    CommonResult,
    GoatsOrderDirection,
    GoatsPriceType,
    MachineContext,
)


# ============================================================
# 期权意图枚举（StockEnum.java:42-79，16 值）
# ============================================================


class OptionIntentionType(str, Enum):
    """对应 Java `stockOptionIntentionType`。"""

    NEW_INQUIRY = "new_inquiry"
    PLACE_ORDER_FROM_QUOTE = "place_order_from_quote"
    CONFIRM_ORDER = "confirm_order"
    CANCEL_ORDER_REQUEST = "cancel_order_request"
    REQUEST_CANCEL_ORDER = "request_cancel_order"
    CONFIRM_CANCEL_ORDER = "confirm_cancel_order"
    REQUEST_MODIFY_ORDER = "request_modify_order"
    CONFIRM_MODIFY_ORDER = "confirm_modify_order"
    QUERY_ORDER_STATUS = "query_order_status"
    CLOSE_ORDER_QUERY = "close_order_query"
    CLOSE_ORDER_REQUEST = "close_order_request"
    CLOSE_ORDER_CONFIRM = "close_order_confirm"
    CLOSE_ORDER_CANCEL_REQUEST = "close_order_cancel_request"
    CLOSE_ORDER_CANCEL_CONFIRM = "close_order_cancel_confirm"
    CLOSE_ORDER_ORDER_QUERY = "close_order_order_query"
    UNKNOWN_INTENT = "unknown_intent"


# ============================================================
# Pydantic ReqVO（对齐 Java FinancialOrderOpenApiBaseSaveReqVO）
# ============================================================


class FinancialOrderOpenApiBaseSaveReqVO(BaseModel):
    """期权下单/操作的单个订单参数（Java DTO 1:1）。"""

    model_config = ConfigDict(extra="allow")

    placeOrderWindCode: str | None = None
    placeOrderPrice: Decimal | None = None
    placeOrderQuantity: int | None = None
    placeOrderOrderType: str | None = None  # BY_QTY / BY_AMOUNT
    placeOrderOrderDirection: GoatsOrderDirection | None = None
    placeOrderPriceType: GoatsPriceType | None = None
    notionalAmount: Decimal | None = None  # 下单金额（向 Goats 发送前要 truncate(2)）
    orderId: str | None = None  # 改单/撤单时填


class CloseOrderReqVO(BaseModel):
    """平仓请求参数。"""

    model_config = ConfigDict(extra="allow")

    contractCode: str | None = None
    qty: int | None = None
    price: Decimal | None = None


class GoatsOptionRfqReqVO(BaseModel):
    """期权询价 / 雪球存量参数（占位，M2 阶段细化）。"""

    model_config = ConfigDict(extra="allow")

    chatType: str | None = None
    chatInstrument: str | None = None
    productType: str | None = None
    tenor: list[str] | None = None
    strike: list[str] | None = None
    knockInPrice: list[str] | None = None
    knockOutPrice: list[str] | None = None
    estimateMargin: list[str] | None = None


class FinancialOrderOpenApiSaveReqVO(BaseModel):
    """`POST /admin-api/financial-orders/operate` 请求体（Java DTO 1:1）。"""

    model_config = ConfigDict(extra="allow")

    operate: str | None = None  # 操作（不强制，与 type 同义但不全等）
    type: OptionIntentionType  # 意图（必填）

    orderList: list[FinancialOrderOpenApiBaseSaveReqVO] = Field(default_factory=list)
    closeOrderReqVO: CloseOrderReqVO | None = None
    optionRfq: GoatsOptionRfqReqVO | None = None

    # 机器人上下文（9 个，由 MachineContext 提供，必填）
    conversationId: str
    messageId: int
    messageContent: str
    rawContent: str
    userId: str
    roomId: str
    quoteContent: str | None = None
    quoteAppinfo: str | None = None
    guid: str | None = None


# ============================================================
# Protocol
# ============================================================


class OptionClient(Protocol):
    """期权操作客户端协议。"""

    async def operate(
        self, req: FinancialOrderOpenApiSaveReqVO
    ) -> CommonResult: ...

    async def query_close_orders(
        self, ctx: MachineContext
    ) -> CommonResult: ...


# ============================================================
# Httpx 实现
# ============================================================


class OptionClientHttpx:
    """走 httpx 的 OptionClient 实现。base_url 指向 mock_api 或真实 Java backend。"""

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        token: str | None = None,
    ) -> None:
        from app.config import get_settings
        settings = get_settings()
        self._base_url = (base_url or settings.otc_api_base_url).rstrip("/")
        self._timeout = timeout
        self._token = token if token is not None else settings.otc_api_secret

    @property
    def _headers(self) -> dict[str, str]:
        from app.tools.auth import get_goats_auth_headers
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        h.update(get_goats_auth_headers())
        return h

    async def operate(
        self, req: FinancialOrderOpenApiSaveReqVO
    ) -> CommonResult:
        url = f"{self._base_url}/admin-api/financial-orders/operate"
        # 金额精度：向 Goats 发送前 truncate 至 2 位
        payload = req.model_dump(mode="json", exclude_none=True)
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            r = await client.post(url, json=payload, headers=self._headers)
            r.raise_for_status()
            return CommonResult.model_validate(r.json())

    async def query_close_orders(
        self, ctx: MachineContext
    ) -> CommonResult:
        url = f"{self._base_url}/admin-api/financial-orders/query-close-orders"
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            r = await client.post(
                url,
                json=ctx.model_dump(mode="json", exclude_none=True),
                headers=self._headers,
            )
            r.raise_for_status()
            return CommonResult.model_validate(r.json())
