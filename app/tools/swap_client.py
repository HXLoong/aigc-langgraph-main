"""SwapClient — POST /admin-api/swap-order/operate（contracts §3）。

承担互换全 7 个意图（SwapIntentionType）。注意：互换的"下单 vs 改单"共用 type=place_order_request，
靠 orderList[i].orderId 是否存在区分。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import ConfigDict, Field, field_serializer, field_validator

from app.tools.http_pool import acquire_http_client
from app.tools.models import (
    GoatsAlgoType,
    GoatsOrderDirection,
    GoatsPriceType,
    GoatsTransactionType,
)
from app.wire_model import WireModel

# ============================================================
# 互换意图枚举（SwapEnum.java:20-43，7 值）
# ============================================================


class SwapIntentionType(StrEnum):
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


class SwapOrderOpenApiBaseSaveReqVO(WireModel):
    """互换下单/操作的单个订单参数（Java DTO 1:1）。"""

    model_config = ConfigDict(extra="allow")

    place_order_wind_code: str | None = Field(default=None, alias="placeOrderWindCode")
    place_order_transaction_type: GoatsTransactionType | None = Field(default=None, alias="placeOrderTransactionType")
    place_order_quantity: int | None = Field(default=None, alias="placeOrderQuantity")
    place_order_quantity_hand: int | None = Field(default=None, alias="placeOrderQuantityHand")
    place_order_order_direction: GoatsOrderDirection | None = Field(default=None, alias="placeOrderOrderDirection")
    place_order_price_type: GoatsPriceType | None = Field(default=None, alias="placeOrderPriceType")
    place_order_price: Decimal | None = Field(default=None, alias="placeOrderPrice")
    place_order_algorithm_type: GoatsAlgoType | None = Field(default=None, alias="placeOrderAlgorithmType")
    place_order_start_time: datetime | None = Field(default=None, alias="placeOrderStartTime")
    place_order_end_time: datetime | None = Field(default=None, alias="placeOrderEndTime")
    order_id: str | None = Field(default=None, alias="orderId")  # 改单时填

    @field_serializer("place_order_start_time", "place_order_end_time", when_used="json")
    def _serialize_order_time(self, value: datetime | None) -> str | None:
        """后端要求秒级本地时间字符串；保留输入时刻的钟面值，不换算时区。"""
        return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else None

    @field_validator('place_order_start_time', 'place_order_end_time', mode="before")
    @classmethod
    def _coerce_short_time(cls, v):  # type: ignore[no-untyped-def]
        """LLM 常输出"HH:MM"/"HH:MM:SS"短时间（算法窗口） → 补今天日期为 datetime。

        完整 ISO 字符串 / datetime 对象 / None 不动，交给 pydantic 默认逻辑。
        """
        if not isinstance(v, str):
            return v
        s = v.strip()
        # "HH:MM" 或 "HH:MM:SS"，且不含日期（无 "-" / "T" / 空格分隔）
        if len(s) <= 8 and ":" in s and "-" not in s and "T" not in s:
            from datetime import date, time
            try:
                parts = [int(x) for x in s.split(":")]
                while len(parts) < 3:
                    parts.append(0)
                t = time(parts[0], parts[1], parts[2])
                return datetime.combine(date.today(), t)
            except (ValueError, IndexError):
                pass
        return v


class SwapOrderOpenApiSaveReqVO(WireModel):
    """`POST /admin-api/swap-order/operate` 请求体（Java DTO 1:1）。"""

    model_config = ConfigDict(extra="allow")

    type: SwapIntentionType  # 意图（必填，互换无 operate 字段）

    order_list: list[SwapOrderOpenApiBaseSaveReqVO] = Field(alias="orderList", default_factory=list)

    # 机器人上下文（9 个）
    conversation_id: str = Field(alias="conversationId")
    message_id: int = Field(alias="messageId")
    message_content: str = Field(alias="messageContent")
    raw_content: str = Field(alias="rawContent")
    user_id: str = Field(alias="userId")
    room_id: str = Field(alias="roomId")
    quote_content: str | None = Field(default=None, alias="quoteContent")
    quote_appinfo: str | None = Field(default=None, alias="quoteAppinfo")
    guid: str | None = None


# ============================================================
# Protocol
# ============================================================


class SwapClient(Protocol):
    """互换操作客户端协议。

    响应一律原样 dict 透传（Java 后端数据不做 Pydantic 建模/校验，2026-09 决定）。
    """

    async def operate(
        self, req: SwapOrderOpenApiSaveReqVO
    ) -> dict[str, Any]: ...

    async def get(self, order_id: str) -> dict[str, Any]: ...

    async def get_conversation_orders(
        self, conversation_id: str
    ) -> dict[str, Any]: ...


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
        timeout: float | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        dry_run: bool | None = None,
    ) -> None:
        """transport 仅测试用；dry_run 为 F4.1 shadow 期写类拦截开关（None=读 settings）。"""
        from app.config import get_settings
        settings = get_settings()
        self._base_url = (base_url or settings.otc_api_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.backend_timeout_seconds
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
    ) -> dict[str, Any]:
        intent_value = req.type.value if hasattr(req.type, "value") else str(req.type)
        if self._dry_run and intent_value not in self._READ_INTENTS:
            from app.observability.metrics import emit_dry_run_intercept

            emit_dry_run_intercept("swap", f"operate:{intent_value}")
            return {
                "code": 0,
                "msg": "dry-run intercepted",
                "data": {"orderId": f"DRY-RUN-{intent_value}"},
            }

        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/swap-order/operate"
        payload = req.model_dump(mode="json", exclude_none=True)
        async with (
            translate_httpx_errors("swap"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.post(url, json=payload, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            response_body: dict[str, Any] = r.json()
            return response_body

    async def get(self, order_id: str) -> dict[str, Any]:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/swap-order/get"
        async with (
            translate_httpx_errors("swap"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.get(url, params={"orderId": order_id}, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            response_body: dict[str, Any] = r.json()
            return response_body

    async def get_conversation_orders(
        self, conversation_id: str
    ) -> dict[str, Any]:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/swap-order/get-conversation-orders"
        async with (
            translate_httpx_errors("swap"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.post(
                url,
                json={"conversationId": conversation_id},
                headers=self._headers,
                timeout=self._timeout,
            )
            r.raise_for_status()
            response_body: dict[str, Any] = r.json()
            return response_body
