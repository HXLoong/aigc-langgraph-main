"""业务客户端只序列化接口值，期限和时间规则由 Java 处理。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.tools.option_client import FinancialOrderOpenApiSaveReqVO, OptionClientHttpx
from app.tools.swap_client import SwapOrderOpenApiSaveReqVO


@pytest.mark.parametrize("product", ["swap", "close"])
async def test_backend_omits_null_literals_without_filling_defaults(monkeypatch, product: str) -> None:
    """业务空占位按新清洗规则省略，仍不能补可平仓过滤默认值。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.subgraphs.close import backend as close_backend
    from app.subgraphs.close.aggregate import build_close_order_req_vo
    from app.subgraphs.swap import backend as swap_backend

    captured = []

    async def operate(request):
        """只替换 Java 边界，记录真实业务提交的 DTO。"""
        captured.append(request.model_dump(by_alias=True, exclude_none=True))
        return {"code": 0, "data": "Java receipt", "msg": ""}

    client = SimpleNamespace(operate=AsyncMock(side_effect=operate))
    state = {"raw_text": "null", "conversation_id": "c", "message_id": 1,
             "room_id": "r", "user_id": "u"}
    if product == "swap":
        monkeypatch.setattr(swap_backend, "SwapClientHttpx", lambda: client)
        await swap_backend.call_swap_backend(state, intent="place_order_request",
                                             order_list=[{"placeOrderWindCode": "null"}])
        assert "placeOrderWindCode" not in captured[0]["orderList"][0]
    else:
        monkeypatch.setattr(close_backend, "OptionClientHttpx", lambda: client)
        request = build_close_order_req_vo(underlying_ins_name_list=["null"])
        await close_backend.call_close_backend(state, intent="close_order_query",
                                               close_order_req_vo=request)
        filters = captured[0]["closeOrderReqVO"]["contractQuery"]
        assert filters["underlyingInsNameList"] == []
        assert "allowCloseOut" not in filters


async def test_option_http_does_not_convert_tenor() -> None:
    """透过真实 HTTP 客户端检查期限原值，没有隐藏的月份换算。"""
    bodies = []

    def respond(request: httpx.Request) -> httpx.Response:
        """HTTP 边界记录实际 body。"""
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "Java card", "msg": ""})

    req = FinancialOrderOpenApiSaveReqVO.model_validate({
        "type": "new_inquiry", "conversationId": "c", "messageId": 1,
        "messageContent": "一年", "rawContent": "一年", "userId": "u", "roomId": "r",
        "orderList": [{"stockCode": "茅台", "tenor": "1Y"}],
    })
    await OptionClientHttpx(base_url="http://java.invalid", token="synthetic",
                            transport=httpx.MockTransport(respond), dry_run=False).operate(req)
    assert bodies[0]["orderList"][0]["tenor"] == "1Y"


def test_swap_serialization_does_not_fill_today_date() -> None:
    """接口支持短时间，客户端不得根据运行日期补出业务日期。"""
    req = SwapOrderOpenApiSaveReqVO.model_validate({
        "type": "place_order_request", "conversationId": "c", "messageId": 1,
        "messageContent": "14:30", "rawContent": "14:30", "userId": "u", "roomId": "r",
        "orderList": [{"placeOrderStartTime": "14:30"}],
    })
    assert req.model_dump(mode="json")["orderList"][0]["placeOrderStartTime"] == "14:30"


async def test_quick_inquiry_keeps_external_parser_values(monkeypatch) -> None:
    """快速询价的外部结果也不经过本地期限换算。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.nodes import fast_query

    requests = []

    async def operate(request):
        """观察快速询价提交的接口值。"""
        requests.append(request.model_dump(exclude_none=True))
        return {"code": 0, "data": "Java quick inquiry", "msg": ""}

    monkeypatch.setattr(fast_query, "_make_agent_client", lambda: SimpleNamespace(
        parse_rfq_instrument=AsyncMock(return_value={"code": 0, "api_data_result_obj": {"tenor": ["1Y"]}}),
    ))
    monkeypatch.setattr(fast_query, "_make_option_client", lambda: SimpleNamespace(operate=operate))
    await fast_query.quick_inquiry({"raw_text": "快速询价一年", "conversation_id": "c",
        "message_id": 1, "room_id": "r", "user_id": "u"})
    assert requests[0]["optionRfq"]["tenor"] == ["1Y"]
