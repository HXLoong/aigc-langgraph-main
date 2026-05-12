"""TickerClient — 标的查询 / 推断 prompt / 交易对手列表（contracts §1）。

特别注意：标的查询是 GET + RequestBody（Java 实现不规范但合法），
要用 `client.request("GET", url, json=payload)` 不能用 `client.get()`。
"""
from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.tools.models import CommonResult

# ============================================================
# Pydantic 模型
# ============================================================


class KeywordItem(BaseModel):
    """关键词查询项。"""

    keyword: str
    isFull: bool = False


class SecuritiesInstrumentReqVO(BaseModel):
    """`GET /admin-api/integration/securities-instrument/select` 请求体（带 Body 的 GET）。"""

    model_config = ConfigDict(extra="allow")

    placeOrderWindCode: str | None = None
    keywordItems: list[KeywordItem] = Field(default_factory=list)
    transactionTypeList: list[str] | None = None


class SecuritiesInstrumentRespVO(BaseModel):
    """对齐 Java `SecuritiesInstrumentOpenApiRespVO`。"""

    model_config = ConfigDict(extra="allow")

    windCode: str
    insShtDesc: str | None = None
    insLngDesc: str | None = None
    relevanceScore: int | None = None
    transactionTypeLists: list[str] = Field(default_factory=list)


class CounterpartyVO(BaseModel):
    """交易对手信息。"""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    code: str | None = None


# ============================================================
# Protocol
# ============================================================


class TickerClient(Protocol):
    """标的相关客户端协议。"""

    async def search_securities_instrument(
        self, req: SecuritiesInstrumentReqVO
    ) -> list[SecuritiesInstrumentRespVO]: ...

    async def get_inference_prompt(self) -> str: ...

    async def list_counterparty(
        self, room_id: str | None = None
    ) -> list[CounterpartyVO]: ...


# ============================================================
# Httpx 实现（注意：select 是 GET + RequestBody，ADR 0012 修订版）
# ============================================================


class TickerClientHttpx:
    """走 httpx 的 TickerClient 实现。"""

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

    async def search_securities_instrument(
        self, req: SecuritiesInstrumentReqVO
    ) -> list[SecuritiesInstrumentRespVO]:
        """⚠️ Java 端是 GET + RequestBody（不规范但合法），要用 client.request("GET", ...) 写法。"""
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/integration/securities-instrument/select"
        payload = req.model_dump(mode="json", exclude_none=True)
        async with (
            translate_httpx_errors("ticker"),
            httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client,
        ):
            r = await client.request("GET", url, json=payload, headers=self._headers)
            r.raise_for_status()
            result = CommonResult.model_validate(r.json())
            data: Any = result.data or []
            return [SecuritiesInstrumentRespVO.model_validate(item) for item in data]

    async def get_inference_prompt(self) -> str:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/counterparty/info/instrument-inference-prompt"
        async with (
            translate_httpx_errors("ticker"),
            httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client,
        ):
            r = await client.get(url, headers=self._headers)
            r.raise_for_status()
            result = CommonResult.model_validate(r.json())
            return str(result.data or "")

    async def list_counterparty(
        self, room_id: str | None = None
    ) -> list[CounterpartyVO]:
        from app.tools.exceptions import translate_httpx_errors

        url = f"{self._base_url}/admin-api/counterparty/info/list"
        params = {"roomId": room_id} if room_id else None
        async with (
            translate_httpx_errors("ticker"),
            httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client,
        ):
            r = await client.get(url, params=params, headers=self._headers)
            r.raise_for_status()
            result = CommonResult.model_validate(r.json())
            data: Any = result.data or []
            return [CounterpartyVO.model_validate(item) for item in data]
