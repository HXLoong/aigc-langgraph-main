"""Persist 节点：把识别到的意图存到后端（审计用）。

对应 Dify 的 `存储消息意图` HTTP 节点。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.nodes.common import safe_node
from app.state import AgentState

logger = logging.getLogger(__name__)


@safe_node
async def persist_intent(state: AgentState) -> dict[str, Any]:
    """把当前识别结果写到后端审计接口。

    非阻塞 —— 失败只记日志，不影响主流程。
    """
    settings = get_settings()
    wx = state["wechat_input"]

    payload = {
        "messageId": wx.get("message_id"),
        "conversationId": wx.get("conversation_id"),
        "roomId": wx.get("room_id"),
        "userId": wx.get("user_id"),
        "productType": state.get("product_type"),
        "intent": state.get("intent"),
        "orderList": state.get("order_list"),
        "apiCode": state.get("api_code"),
        "apiResult": state.get("api_result"),
        "error": state.get("error"),
    }

    try:
        async with httpx.AsyncClient(
            base_url=settings.otc_api_base_url,
            headers={"Authorization": settings.otc_api_secret},
            timeout=5.0,
        ) as client:
            r = await client.post(
                "/admin-api/openapi/xbot/message/set-intent",
                json=payload,
            )
            r.raise_for_status()
    except Exception as e:
        logger.warning("persist_intent 失败（非致命）: %s", e)
        return {"trace": [{"node": "persist_intent", "status": "error", "error": str(e)}]}

    return {"trace": [{"node": "persist_intent", "status": "success"}]}
