"""消息会话与意图写回（Java /openapi/xbot/message/set-intent）。

响应原样 dict 透传（Java 后端数据不做 Pydantic 建模/校验，2026-09 决定）；
写回 ACK 判定（`code` 显式为 0）保留在原始 dict 上。
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal, Protocol, cast

import httpx
from pydantic import ConfigDict, Field

from app.tools.auth import get_goats_auth_headers
from app.wire_model import WireModel


class SetIntentRequest(WireModel):
    """保留 Java camelCase 字段；会话 ID 为不透明字符串。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    conversation_id: str = Field(alias="conversationId")
    message_id: str = Field(alias="messageId")
    intent: str
    product_type: Literal[0, 1] = Field(alias="productType")
    order_ids: list[str] = Field(alias="orderIds", default_factory=list, max_length=0)


class SetIntentError(RuntimeError):
    """消息持久化失败；仅携带错误类别，不包含 URL、Token 或后端正文。"""


class MessageClient(Protocol):
    """写回消息元数据；成功返回原始响应 dict（code=0），失败抛异常。"""

    async def set_intent(self, req: SetIntentRequest) -> dict[str, Any]: ...


class MessageClientHttpx:
    """复用 Java URL、平台 Token 和 GOATS 签名，不受交易 dry-run 开关影响。"""

    def __init__(
        self,
        base_url: str = "",
        timeout: float | None = None,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        from app.config import get_settings

        settings = get_settings()
        self._base_url = (base_url or settings.otc_api_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.backend_timeout_seconds
        self._token = token if token is not None else settings.otc_api_secret
        self._transport = transport

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        headers.update(get_goats_auth_headers())
        return headers

    async def set_intent(self, req: SetIntentRequest) -> dict[str, Any]:
        """仅超时、连接失败及 5xx 在 100ms 后重试一次。"""
        payload = req.model_dump(mode="json")
        async with httpx.AsyncClient(
            timeout=self._timeout, trust_env=False, transport=self._transport,
        ) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        f"{self._base_url}/admin-api/openapi/xbot/message/set-intent",
                        json=payload,
                        headers=self._headers,
                    )
                except httpx.TimeoutException:
                    reason = "timeout"
                except httpx.ConnectError:
                    reason = "connect_error"
                except httpx.RequestError:
                    raise SetIntentError("set-intent: transport_error") from None
                else:
                    if response.is_success:
                        try:
                            payload_json = response.json()
                        except ValueError:
                            raise SetIntentError("set-intent: invalid_response") from None
                        # 透传原始响应；只做写回 ACK 判定：`code` 必须显式为非 bool 整数 0
                        # （dict 缺失 / 类型异常 / bool False 都不能证明写回成功）。
                        code = payload_json.get("code") if isinstance(payload_json, dict) else None
                        if not isinstance(code, int) or isinstance(code, bool):
                            raise SetIntentError("set-intent: invalid_response")
                        if code != 0:
                            raise SetIntentError("set-intent: business_error")
                        return cast(dict[str, Any], payload_json)
                    reason = f"http_{response.status_code}"
                    if not response.is_server_error:
                        raise SetIntentError(f"set-intent: {reason}")

                # 在 except 之外抛出，避免 safe_node 的 traceback 包含底层请求详情。
                if attempt == 1:
                    raise SetIntentError(f"set-intent: {reason}")
                await asyncio.sleep(0.1)

        raise AssertionError("unreachable")
