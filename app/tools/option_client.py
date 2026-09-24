"""OptionClient — POST /admin-api/financial-orders/operate（contracts §2）。

承担期权全 16 个意图（stockOptionIntentionType）：询价 / 下单 / 改单 / 撤单 / 平仓 / 查询 / 确认。
"""
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import ConfigDict, Field, field_validator

from app.extraction.tenor import normalize_request_tenors
from app.tools.http_pool import acquire_http_client
from app.tools.models import (
    GoatsOrderDirection,
    GoatsPriceType,
)
from app.wire_model import WireModel

# ============================================================
# 期权意图枚举（StockEnum.java:42-79，16 值）
# ============================================================


class OptionIntentionType(StrEnum):
    """对应 Java `stockOptionIntentionType`（contracts §2.1，16 值，Java 后端真实契约）。

    注意：`REQUEST_MODIFY_ORDER` / `CONFIRM_MODIFY_ORDER` 在 Dify DSL v2 迁移后
    的「期权-意图识别」LLM 节点枚举里已不再出现——期权域不再有独立改单流程，
    对已有订单的参数修改统一由意图分类器归为 `place_order_from_quote`（见
    `app/prompts/option/intent.md` 规则1第7条），因此 `app/subgraphs/option/`
    没有任何节点会产出这两个值。但本枚举镜像的是 Java 后端的真实契约
    （docs/api-contracts/java-backend.md §2.1），后端仍可能接受这两个历史意图
    （如其他调用方/运维通道），故保留不删，避免请求校验层收窄真实契约。
    """

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


class FinancialOrderOpenApiBaseSaveReqVO(WireModel):
    """期权下单/操作的单个订单参数（Java DTO 1:1）。"""

    model_config = ConfigDict(extra="allow")

    place_order_wind_code: str | None = Field(default=None, alias="placeOrderWindCode")
    place_order_price: Decimal | None = Field(default=None, alias="placeOrderPrice")
    place_order_quantity: int | None = Field(default=None, alias="placeOrderQuantity")
    place_order_order_type: str | None = Field(default=None, alias="placeOrderOrderType")  # BY_QTY / BY_AMOUNT
    place_order_order_direction: GoatsOrderDirection | None = Field(default=None, alias="placeOrderOrderDirection")
    place_order_price_type: GoatsPriceType | None = Field(default=None, alias="placeOrderPriceType")
    notional_amount: Decimal | None = Field(default=None, alias="notionalAmount")  # 下单金额（向 Goats 发送前要 truncate(2)）
    order_id: str | None = Field(default=None, alias="orderId")  # 改单/撤单时填


class CloseOrderReqVO(WireModel):
    """平仓请求参数。"""

    model_config = ConfigDict(extra="allow")

    contract_code: str | None = Field(default=None, alias="contractCode")
    qty: int | None = None
    price: Decimal | None = None


class GoatsOptionRfqReqVO(WireModel):
    """期权询价 / 雪球参数；GOATS 数值数组在请求边界转成字符串数组。"""

    model_config = ConfigDict(extra="allow")

    chat_type: str | None = Field(default=None, alias="chatType")
    chat_instrument: str | None = Field(default=None, alias="chatInstrument")
    product_type: str | None = Field(default=None, alias="productType")
    tenor: list[str] | None = None
    strike: list[str] | None = None
    knock_in_price: list[str] | None = Field(default=None, alias="knockInPrice")
    knock_out_price: list[str] | None = Field(default=None, alias="knockOutPrice")
    estimate_margin: list[str] | None = Field(default=None, alias="estimateMargin")
    participate_rate: list[str] | None = Field(default=None, alias="participateRate")

    @field_validator(
        "strike", 'knock_in_price', 'knock_out_price', 'estimate_margin', 'participate_rate',
        mode="before",
    )
    @classmethod
    def normalize_numeric_arrays(cls, value: Any) -> Any:
        # 保持 0.8 的比例语义，只转换类型；字符串、空值及扩展字段原样保留。
        if isinstance(value, list):
            return [
                str(item)
                if isinstance(item, (int, float, Decimal)) and not isinstance(item, bool)
                else item
                for item in value
            ]
        return value


class FinancialOrderOpenApiSaveReqVO(WireModel):
    """`POST /admin-api/financial-orders/operate` 请求体（Java DTO 1:1）。

    字段对齐 Dify DSL v2 code 节点「期权开仓」（spec/code_nodes/期权开仓.py）
    组装的 payload：conversationId / messageId / messageContent / quoteAppinfo /
    roomId / guid / userId / type / operate / operatorUserId / orderList /
    rawContent / quoteContent。
    """

    model_config = ConfigDict(extra="allow")

    operate: str | None = None  # 操作（不强制，与 type 同义但不全等）
    type: OptionIntentionType  # 意图（必填）

    order_list: list[FinancialOrderOpenApiBaseSaveReqVO] = Field(alias="orderList", default_factory=list)
    close_order_req_vo: CloseOrderReqVO | None = Field(default=None, alias="closeOrderReqVO")
    option_rfq: GoatsOptionRfqReqVO | None = Field(default=None, alias="optionRfq")

    # 机器人上下文（9 个，由 MachineContext 提供，必填）
    conversation_id: str = Field(alias="conversationId")
    message_id: int = Field(alias="messageId")
    message_content: str = Field(alias="messageContent")
    raw_content: str = Field(alias="rawContent")
    user_id: str = Field(alias="userId")
    room_id: str = Field(alias="roomId")
    quote_content: str | None = Field(default=None, alias="quoteContent")
    quote_appinfo: str | None = Field(default=None, alias="quoteAppinfo")
    guid: str | None = None
    #: 人工兜底代客操作人（本人操作时为空）；对齐 Dify `operator_user_id` 变量
    operator_user_id: str | None = Field(default=None, alias="operatorUserId")


# ============================================================
# Protocol
# ============================================================


class OptionClient(Protocol):
    """期权操作客户端协议。

    响应一律原样 dict 透传（Java 后端数据不做 Pydantic 建模/校验，2026-09 决定）。
    """

    async def operate(
        self, req: FinancialOrderOpenApiSaveReqVO
    ) -> dict[str, Any]: ...

    async def query_close_orders(
        self,
        order_ids: list[str] | None = None,
        contract_codes: list[str] | None = None,
    ) -> dict[str, Any]: ...


# ============================================================
# Httpx 实现
# ============================================================


class OptionClientHttpx:
    """走 httpx 的 OptionClient 实现。"""

    #: shadow / dry-run 期写类拦截白名单的"反向集合"——出现在此集合的 intent 视为 read，
    #: 即使调 operate endpoint 也不拦截。详见 docs/deploy/shadow-compare-guide.md
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
        timeout: float | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        dry_run: bool | None = None,
    ) -> None:
        """
        Args:
            transport: 仅测试用，可注入自定义 transport。生产环境不传，保持 None。
            dry_run: shadow 双跑用。True → 写类 intent 调用被拦截；None → 从
                Settings.dry_run_backend 读取。
        """
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

    def _client_kwargs(self) -> dict[str, Any]:
        """httpx.AsyncClient 构造参数（测试期可注入 transport）。"""
        kw: dict[str, Any] = {"timeout": self._timeout, "trust_env": False}
        if self._transport is not None:
            kw["transport"] = self._transport
        return kw

    async def operate(
        self, req: FinancialOrderOpenApiSaveReqVO
    ) -> dict[str, Any]:
        intent_value = req.type.value if hasattr(req.type, "value") else str(req.type)
        if self._dry_run and intent_value not in self._READ_INTENTS:
            from app.observability.metrics import emit_dry_run_intercept
            from app.tools.receipts import DRY_RUN_REPLY

            emit_dry_run_intercept("option", f"operate:{intent_value}")
            return {
                "code": 0,
                "msg": "dry-run intercepted",
                "data": DRY_RUN_REPLY,
            }

        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/financial-orders/operate"
        # 金额精度：向 Goats 发送前 truncate 至 2 位
        payload = normalize_request_tenors(req.model_dump(mode="json", exclude_none=True))
        async with (
            translate_httpx_errors("option"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.post(url, json=payload, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            response_body: dict[str, Any] = r.json()
            return response_body

    async def query_close_orders(
        self,
        order_ids: list[str] | None = None,
        contract_codes: list[str] | None = None,
        room_id: str | None = None,
        message_id: int | None = None,
    ) -> dict[str, Any]:
        """查可平仓订单数据（contracts §2.x）。

        真后端按 orderIds + contractCodes 过滤；roomId/messageId 对齐
        DSL v2「获取订单信息」http 节点 payload（P3 迁移 follow-up）。
        """
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/financial-orders/query-close-orders"
        payload: dict[str, Any] = {
            "orderIds": order_ids or [],
            "contractCodes": contract_codes or [],
        }
        if room_id is not None:
            payload["roomId"] = room_id
        if message_id is not None:
            payload["messageId"] = message_id
        async with (
            translate_httpx_errors("option"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.post(url, json=payload, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            response_body: dict[str, Any] = r.json()
            return response_body
