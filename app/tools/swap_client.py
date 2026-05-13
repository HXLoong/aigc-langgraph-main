"""SwapClient — POST /admin-api/swap-order/operate（contracts §3）。

承担互换全 7 个意图（SwapIntentionType）。注意：互换的"下单 vs 改单"共用 type=place_order_request，
靠 orderList[i].orderId 是否存在区分。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.tools.models import (
    CommonResult,
    GoatsAlgoType,
    GoatsOrderDirection,
    GoatsPriceType,
    GoatsTransactionType,
)

# ============================================================
# 互换意图枚举（SwapEnum.java:20-43，7 值）
# ============================================================


class SwapIntentionType(str, Enum):
    """对应 Java `SwapIntentionType`。"""

    PLACE_ORDER_REQUEST = "place_order_request"  # 请求下单/改单（合一）
    CONFIRM_ORDER = "confirm_order"
    CANCEL_ORDER_REQUEST = "cancel_order_request"
    CONFIRM_CANCEL_ORDER = "confirm_cancel_order"
    CONFIRM_MODIFY_ORDER = "confirm_modify_order"
    QUERY_ORDER_STATUS = "query_order_status"
    UNKNOWN_INTENT = "unknown_intent"


# ============================================================
# Pydantic ReqVO（对齐 Java SwapOrderOpenApiBaseSaveReqVO）
# ============================================================


class SwapOrderOpenApiBaseSaveReqVO(BaseModel):
    """互换下单/操作的单个订单参数（Java DTO 1:1）。"""

    model_config = ConfigDict(extra="allow")

    placeOrderWindCode: str | None = None
    placeOrderTransactionType: GoatsTransactionType | None = None
    placeOrderQuantity: int | None = None
    placeOrderQuantityHand: int | None = None
    placeOrderOrderDirection: GoatsOrderDirection | None = None
    placeOrderPriceType: GoatsPriceType | None = None
    placeOrderPrice: Decimal | None = None
    placeOrderAlgorithmType: GoatsAlgoType | None = None
    placeOrderStartTime: datetime | None = None
    placeOrderEndTime: datetime | None = None
    orderId: str | None = None  # 改单时填


class SwapOrderOpenApiSaveReqVO(BaseModel):
    """`POST /admin-api/swap-order/operate` 请求体（Java DTO 1:1）。"""

    model_config = ConfigDict(extra="allow")

    type: SwapIntentionType  # 意图（必填，互换无 operate 字段）

    orderList: list[SwapOrderOpenApiBaseSaveReqVO] = Field(default_factory=list)

    # 机器人上下文（9 个）
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


class SwapClient(Protocol):
    """互换操作客户端协议。"""

    async def operate(
        self, req: SwapOrderOpenApiSaveReqVO
    ) -> CommonResult: ...

    async def get(self, order_id: str) -> CommonResult: ...

    async def get_conversation_orders(
        self, conversation_id: str
    ) -> CommonResult: ...


# ============================================================
# Httpx 实现
# ============================================================


class SwapClientHttpx:
    """走 httpx 的 SwapClient 实现。"""

    #: F4.1 shadow 期 read 类 intent 白名单（即使调 operate 也不 dry-run 拦截）
    _READ_INTENTS: frozenset[str] = frozenset({
        "query_order_status",  # 查订单状态
        "unknown_intent",      # 兜底
    })

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        dry_run: bool | None = None,
    ) -> None:
        """transport 仅测试用；dry_run 为 F4.1 shadow 期写类拦截开关（None=读 settings）。"""
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
        self, req: SwapOrderOpenApiSaveReqVO
    ) -> CommonResult:
        intent_value = req.type.value if hasattr(req.type, "value") else str(req.type)
        if self._dry_run and intent_value not in self._READ_INTENTS:
            from app.observability.metrics import emit_dry_run_intercept

            emit_dry_run_intercept("swap", f"operate:{intent_value}")
            return CommonResult(
                code=0,
                msg="dry-run intercepted",
                data={"orderId": f"DRY-RUN-{intent_value}"},
            )

        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/swap-order/operate"
        payload = req.model_dump(mode="json", exclude_none=True)
        async with (
            translate_httpx_errors("swap"),
            httpx.AsyncClient(**self._client_kwargs()) as client,
        ):
            r = await client.post(url, json=payload, headers=self._headers)
            r.raise_for_status()
            return CommonResult.model_validate(r.json())

    async def get(self, order_id: str) -> CommonResult:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/swap-order/get"
        async with (
            translate_httpx_errors("swap"),
            httpx.AsyncClient(**self._client_kwargs()) as client,
        ):
            r = await client.get(url, params={"orderId": order_id}, headers=self._headers)
            r.raise_for_status()
            return CommonResult.model_validate(r.json())

    async def get_conversation_orders(
        self, conversation_id: str
    ) -> CommonResult:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/swap-order/get-conversation-orders"
        async with (
            translate_httpx_errors("swap"),
            httpx.AsyncClient(**self._client_kwargs()) as client,
        ):
            r = await client.post(
                url,
                json={"conversationId": conversation_id},
                headers=self._headers,
            )
            r.raise_for_status()
            return CommonResult.model_validate(r.json())
