"""互换时间接口只做传输，不补日期、不改原文中的时区或精度。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.tools.swap_client import SwapClientHttpx, SwapOrderOpenApiSaveReqVO


@pytest.mark.parametrize("start,end", [
    ("14:00", "15:00"), ("14:30:45", None),
    ("2026-09-18T09:30:00.123456+08:00", "2026-09-18T15:00:00+08:00"),
    ("not-a-time", None),
])
async def test_time_strings_reach_java_unchanged(start, end):
    """业务有效性留给 Java；验证真实客户端不会隐藏补齐或截断。"""
    sent = []

    def response(request):
        """截取实际 HTTP JSON，接口原始拒绝同样向上返回。"""
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 400, "msg": "Java时间校验"})

    order = {"placeOrderStartTime": start}
    if end is not None:
        order["placeOrderEndTime"] = end
    request = SwapOrderOpenApiSaveReqVO(type="place_order_request", orderList=[order],
        conversationId="c", messageId=1, messageContent="raw", rawContent="raw", userId="u", roomId="r")
    result = await SwapClientHttpx(base_url="http://test", transport=httpx.MockTransport(response), dry_run=False).operate(request)
    assert sent[0]["orderList"] == [order]
    assert result["code"] == 400 and result["msg"] == "Java时间校验"
