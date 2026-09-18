"""TickerClient — 标的查询 / 推断 prompt / 交易对手列表（contracts §1）。

特别注意：标的查询是 GET + RequestBody（Java 实现不规范但合法），
要用 `client.request("GET", url, json=payload)` 不能用 `client.get()`。

响应一律原样 dict 透传（Java 后端数据不做 Pydantic 建模/校验，2026-09 决定）。
"""
from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import ConfigDict, Field

from app.tools.http_pool import acquire_http_client
from app.wire_model import WireModel

# ============================================================
# Pydantic 模型
# ============================================================


class KeywordItem(WireModel):
    """关键词查询项。"""

    keyword: str
    is_full: bool = Field(default=False, alias="isFull")


class SecuritiesInstrumentReqVO(WireModel):
    """`GET /admin-api/integration/securities-instrument/select` 请求体（带 Body 的 GET）。"""

    model_config = ConfigDict(extra="allow")

    place_order_wind_code: str | None = Field(default=None, alias="placeOrderWindCode")
    keyword_items: list[KeywordItem] = Field(alias="keywordItems", default_factory=list)
    transaction_type_list: list[str] | None = Field(default=None, alias="transactionTypeList")


# ============================================================
# Protocol
# ============================================================


class TickerClient(Protocol):
    """标的相关客户端协议。"""

    async def search_securities_instrument(
        self, req: SecuritiesInstrumentReqVO
    ) -> list[dict[str, Any]]: ...

    async def get_inference_prompt(self) -> str: ...

    async def list_counterparty(
        self, room_id: str | None = None, *, user_id: str | None = None,
        business_type: str | None = None, message_id: int | None = None,
    ) -> list[dict[str, Any]]: ...


# ============================================================
# Httpx 实现（注意：select 是 GET + RequestBody，ADR 0012 修订版）
# ============================================================


class TickerClientHttpx:
    """走 httpx 的 TickerClient 实现。"""

    def __init__(
        self,
        base_url: str = "",
        timeout: float | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """transport 仅测试用，可注入自定义 transport。生产环境不传，保持 None。"""
        from app.config import get_settings
        settings = get_settings()
        self._base_url = (base_url or settings.otc_api_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.backend_timeout_seconds
        self._token = token if token is not None else settings.otc_api_secret
        self._transport = transport

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

    async def search_securities_instrument(
        self, req: SecuritiesInstrumentReqVO
    ) -> list[dict[str, Any]]:
        """⚠️ Java 端是 GET + RequestBody（不规范但合法），要用 client.request("GET", ...) 写法。"""
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/integration/securities-instrument/select"
        payload = req.model_dump(mode="json", exclude_none=True)
        async with (
            translate_httpx_errors("ticker"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.request("GET", url, json=payload, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            envelope: dict[str, Any] = r.json()
            rows: list[dict[str, Any]] = envelope.get("data") or []
            return rows

    async def get_inference_prompt(self) -> str:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/counterparty/info/instrument-inference-prompt"
        async with (
            translate_httpx_errors("ticker"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.get(url, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            envelope: dict[str, Any] = r.json()
            return str(envelope.get("data") or "")

    async def list_counterparty(
        self, room_id: str | None = None, *, user_id: str | None = None,
        business_type: str | None = None, message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/counterparty/info/list"
        params = {key: str(value) for key, value in {
            "roomId": room_id, "userId": user_id, "type": business_type, "messageId": message_id,
        }.items() if value is not None}
        async with (
            translate_httpx_errors("ticker"),
            acquire_http_client(timeout=self._timeout, transport=self._transport) as client,
        ):
            r = await client.get(url, params=params, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            envelope: dict[str, Any] = r.json()
            if envelope.get("code") != 0:
                raise ValueError(f"counterparty lookup failed: code={envelope.get('code')}")
            rows: list[dict[str, Any]] = envelope.get("data") or []
            return rows
