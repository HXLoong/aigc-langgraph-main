"""TickerClient — 授权交易对手列表（仅本地验收脚本使用，交易链路不调用）。

标的识别归 Java 后端（ADR 0025），本客户端不提供标的查询。
响应一律原样 dict 透传（Java 后端数据不做 Pydantic 建模/校验）。
"""
from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.tools.http_pool import acquire_http_client

# ============================================================
# Protocol
# ============================================================


class TickerClient(Protocol):
    """交易对手列表客户端协议。"""

    async def list_counterparty(
        self, room_id: str | None = None, *, user_id: str | None = None,
        business_type: str | None = None, message_id: int | None = None,
    ) -> list[dict[str, Any]]: ...


# ============================================================
# Httpx 实现
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

    def _client_kwargs(self) -> dict[str, Any]:
        """httpx.AsyncClient 构造参数（测试期可注入 transport）。"""
        kw: dict[str, Any] = {"timeout": self._timeout, "trust_env": False}
        if self._transport is not None:
            kw["transport"] = self._transport
        return kw

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
