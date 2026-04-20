"""后端业务 API 客户端。

统一封装对 otc-backend 的所有 HTTP 调用，包括：
- /admin-api/swap-order/operate          互换订单操作
- /admin-api/option-order/operate        期权订单操作
- /admin-api/financial-orders/operate    期权平仓
- /admin-api/openapi/xbot/message/set-intent   意图审计

特点：
1. 异步、带重试、带超时
2. 统一的错误码处理（code=0 成功，code=500 服务不可用，其他为业务错误）
3. 全部请求记 trace，便于排查
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = logging.getLogger(__name__)


class OtcBackendError(Exception):
    """后端业务异常。"""
    def __init__(self, code: int, msg: str, endpoint: str) -> None:
        self.code = code
        self.msg = msg
        self.endpoint = endpoint
        super().__init__(f"{endpoint}: code={code}, msg={msg}")


class OtcBackendClient:
    """后端业务 API 客户端。"""

    def __init__(self, base_url: str | None = None, secret: str | None = None) -> None:
        settings = get_settings()
        self.base_url = base_url or settings.otc_api_base_url
        self.secret = secret or settings.otc_api_secret
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OtcBackendClient:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": self.secret,
            },
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("必须在 async with 上下文中使用")
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4.0),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )
    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._ensure_client()
        r = await client.post(path, json=payload)
        r.raise_for_status()
        return r.json()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4.0),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )
    async def _get(self, path: str) -> dict[str, Any]:
        client = self._ensure_client()
        r = await client.get(path)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------
    # 互换
    # ------------------------------------------------------------
    async def swap_operate(
        self,
        *,
        conversation_id: str,
        message_id: str,
        message_content: str,
        raw_content: str,
        quote_content: str | None,
        quote_appinfo: str | None,
        user_id: str,
        room_id: str,
        guid: str,
        type_: str,
        order_list: list[dict],
    ) -> dict[str, Any]:
        """调用 /admin-api/swap-order/operate。

        对应 Dify 互换工具的 `互换API` 节点。
        """
        payload = {
            "conversationId": conversation_id,
            "messageId": message_id,
            "messageContent": message_content,
            "rawContent": raw_content,
            "quoteContent": quote_content,
            "quoteAppinfo": quote_appinfo,
            "userId": user_id,
            "roomId": room_id,
            "guid": guid,
            "type": type_,
            "orderList": order_list,
        }
        try:
            resp = await self._post("/admin-api/swap-order/operate", payload)
            return self._normalize(resp, "swap_operate")
        except httpx.HTTPError as e:
            logger.exception("swap_operate HTTP 错误")
            return {"code": 500, "result": "交易指令服务暂不可用", "error": str(e)}

    # ------------------------------------------------------------
    # 期权
    # ------------------------------------------------------------
    async def option_operate(
        self,
        *,
        conversation_id: str,
        message_id: str,
        message_content: str,
        raw_content: str,
        quote_content: str | None,
        quote_appinfo: str | None,
        user_id: str,
        room_id: str,
        guid: str,
        operate: str,
        type_: str,
        order_list: list[dict],
    ) -> dict[str, Any]:
        """调用 /admin-api/option-order/operate。"""
        payload = {
            "conversationId": conversation_id,
            "messageId": message_id,
            "messageContent": message_content,
            "rawContent": raw_content,
            "quoteContent": quote_content,
            "quoteAppinfo": quote_appinfo,
            "userId": user_id,
            "roomId": room_id,
            "guid": guid,
            "operate": operate,
            "type": type_,
            "orderList": order_list,
        }
        try:
            resp = await self._post("/admin-api/option-order/operate", payload)
            return self._normalize(resp, "option_operate")
        except httpx.HTTPError as e:
            logger.exception("option_operate HTTP 错误")
            return {"code": 500, "result": "交易指令服务暂不可用", "error": str(e)}

    # ------------------------------------------------------------
    # 期权平仓（统一接口）
    # ------------------------------------------------------------
    async def financial_orders_operate(
        self, **payload: Any,
    ) -> dict[str, Any]:
        """调用 /admin-api/financial-orders/operate（持仓查询、下单、撤单）。"""
        try:
            resp = await self._post("/admin-api/financial-orders/operate", payload)
            return self._normalize(resp, "financial_orders_operate")
        except httpx.HTTPError as e:
            logger.exception("financial_orders_operate HTTP 错误")
            return {"code": 500, "result": "期权平仓服务暂不可用", "error": str(e)}

    # ------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------
    async def counterparty_list(self) -> list[dict[str, Any]]:
        try:
            resp = await self._get("/admin-api/counterparty/info/list")
            return resp.get("data") or []
        except httpx.HTTPError as e:
            logger.warning("counterparty_list 失败: %s", e)
            return []

    async def conversation_orders(
        self,
        conversation_id: str,
        user_id: str,
        room_id: str,
    ) -> list[dict[str, Any]]:
        try:
            resp = await self._post(
                "/admin-api/swap-order/get-conversation-orders",
                {
                    "conversationId": conversation_id,
                    "userId": user_id,
                    "roomId": room_id,
                },
            )
            return resp.get("data") or []
        except httpx.HTTPError as e:
            logger.warning("conversation_orders 失败: %s", e)
            return []

    async def bot_name_list(self) -> list[str]:
        try:
            resp = await self._get("/admin-api/openapi/xbot/bot/name-list")
            return resp.get("data") or []
        except httpx.HTTPError as e:
            logger.warning("bot_name_list 失败: %s", e)
            return []

    async def set_intent(self, **payload: Any) -> None:
        try:
            await self._post("/admin-api/openapi/xbot/message/set-intent", payload)
        except httpx.HTTPError as e:
            logger.warning("set_intent 失败: %s", e)

    # ------------------------------------------------------------
    # 内部：统一响应结构
    # ------------------------------------------------------------
    @staticmethod
    def _normalize(resp: dict[str, Any], endpoint: str) -> dict[str, Any]:
        code = resp.get("code")
        if code == 0:
            return {"code": 0, "result": resp.get("data", "")}
        if code == 500:
            return {"code": 500, "result": "交易指令服务暂不可用"}
        return {
            "code": code if isinstance(code, int) else -1,
            "result": resp.get("msg", "未知错误"),
        }
