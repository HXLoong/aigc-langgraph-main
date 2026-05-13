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
        self,
        order_ids: list[str] | None = None,
        contract_codes: list[str] | None = None,
    ) -> CommonResult: ...


# ============================================================
# Httpx 实现
# ============================================================


class OptionClientHttpx:
    """走 httpx 的 OptionClient 实现。base_url 指向 mock_api 或真实 Java backend。"""

    #: F4.1 shadow 期写类拦截白名单的"反向集合"——出现在此集合的 intent 视为 read，
    #: 即使调 operate endpoint 也不拦截。详见 docs/m3-shadow-compare-dry-run-design.md
    _READ_INTENTS: frozenset[str] = frozenset({
        "new_inquiry",           # 询价不下单
        "query_order_status",    # 查订单状态
        "close_order_query",     # 查持仓/可平仓
        "close_order_order_query",  # 查平仓订单
        "unknown_intent",        # 兜底
    })

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        dry_run: bool | None = None,
    ) -> None:
        """
        Args:
            transport: 仅测试用。注入 httpx.ASGITransport(mock_api.app) 即可
                把 client 切到 mock_api 的内存 FastAPI 实例上跑（无端口）。
                生产环境**不传**此参数，保持 None。
            dry_run: F4.1 shadow 双跑用。True → 写类 intent 调用被拦截，返回
                fake CommonResult；read 类 intent 仍真调。None → 从
                Settings.dry_run_backend 读取（生产环境通常 False）。
        """
        from app.config import get_settings
        settings = get_settings()
        self._base_url = (base_url or settings.otc_api_base_url).rstrip("/")
        self._timeout = timeout
        self._token = token if token is not None else settings.otc_api_secret
        self._transport = transport
        self._dry_run = (
            settings.dry_run_backend if dry_run is None else dry_run
        )

    @property
    def _headers(self) -> dict[str, str]:
        from app.tools.auth import get_goats_auth_headers
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        h.update(get_goats_auth_headers())
        return h

    def _client_kwargs(self) -> dict:
        """httpx.AsyncClient 构造参数（测试期可注入 transport）。"""
        kw = {"timeout": self._timeout, "trust_env": False}
        if self._transport is not None:
            kw["transport"] = self._transport
        return kw

    async def operate(
        self, req: FinancialOrderOpenApiSaveReqVO
    ) -> CommonResult:
        intent_value = req.type.value if hasattr(req.type, "value") else str(req.type)
        if self._dry_run and intent_value not in self._READ_INTENTS:
            from app.observability.metrics import emit_dry_run_intercept

            emit_dry_run_intercept("option", f"operate:{intent_value}")
            return CommonResult(
                code=0,
                msg="dry-run intercepted",
                data={"orderId": f"DRY-RUN-{intent_value}"},
            )

        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/financial-orders/operate"
        # 金额精度：向 Goats 发送前 truncate 至 2 位
        payload = req.model_dump(mode="json", exclude_none=True)
        async with (
            translate_httpx_errors("option"),
            httpx.AsyncClient(**self._client_kwargs()) as client,
        ):
            r = await client.post(url, json=payload, headers=self._headers)
            r.raise_for_status()
            return CommonResult.model_validate(r.json())

    async def query_close_orders(
        self,
        order_ids: list[str] | None = None,
        contract_codes: list[str] | None = None,
    ) -> CommonResult:
        """查可平仓订单数据（contracts §2.x）。

        真后端按 orderIds + contractCodes 过滤；签名修正于 #80 follow-up，
        旧 signature `(ctx: MachineContext)` 实际与真后端 endpoint 不兼容，
        且无生产 caller。
        """
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/financial-orders/query-close-orders"
        payload = {
            "orderIds": order_ids or [],
            "contractCodes": contract_codes or [],
        }
        async with (
            translate_httpx_errors("option"),
            httpx.AsyncClient(**self._client_kwargs()) as client,
        ):
            r = await client.post(url, json=payload, headers=self._headers)
            r.raise_for_status()
            return CommonResult.model_validate(r.json())
