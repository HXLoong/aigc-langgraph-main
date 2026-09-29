"""BotContext：协议层只吃机器人上下文，不吃整个 AgentState（ADR 0024 D3）。"""
from __future__ import annotations

from app.tools.bot_context import BotContext


def _state() -> dict:
    return {
        "raw_text": "腾讯 1000 股",
        "quote_content": "订单 H-1",
        "quote_appinfo": None,
        "conversation_id": "conv-1",
        "message_id": "msg-20260917-000042",
        "user_id": "u1",
        "room_id": "r1",
        "guid": "g1",
        "operator_user_id": "op1",
        "tickers": [],  # 业务对象不属于上下文
        "place_params": {"orderList": []},
    }


def test_from_state_normalizes_message_id_and_ignores_business_objects() -> None:
    ctx = BotContext.from_state(_state())
    assert ctx.message_id == 20260917000042
    assert ctx.conversation_id == "conv-1"
    assert "tickers" not in ctx.model_fields and "place_params" not in ctx.model_fields


def test_missing_required_lists_absent_context_fields() -> None:
    ctx = BotContext.from_state({"raw_text": "x", "message_id": "no-digits"})
    assert ctx.missing_required() == ["conversation_id", "room_id", "user_id", "message_id"]
    assert BotContext.from_state(_state()).missing_required() == []


def test_to_wire_matches_legacy_context_shape_byte_for_byte() -> None:
    """三个子图 backend 里重复的 _context() 曾各自维护这一份 dict；现在只在这里定义一次。"""
    assert BotContext.from_state(_state()).to_wire() == {
        "conversationId": "conv-1",
        "messageId": 20260917000042,
        "messageContent": "腾讯 1000 股\n订单 H-1",
        "rawContent": "腾讯 1000 股",
        "quoteContent": "订单 H-1",
        "quoteAppinfo": None,
        "userId": "u1",
        "roomId": "r1",
        "guid": "g1",
        "operatorUserId": "op1",
    }
    bare = BotContext.from_state({"raw_text": "只有原文"}).to_wire()
    assert bare["messageContent"] == "只有原文" and bare["messageId"] == 0 and bare["userId"] == ""


async def test_backends_build_context_from_bot_context(monkeypatch) -> None:
    """经真实 HTTP 客户端验证上下文，后端实现移动到公共边界不改变 wire。"""
    import json
    from importlib import import_module

    import httpx

    for product, intent in (("option", "query_order_status"), ("swap", "query_order_status"), ("close", "close_order_query")):
        module = import_module(f"app.subgraphs.{product}.backend")
        client_class = module.SwapClientHttpx if product == "swap" else module.OptionClientHttpx
        sent = []

        def respond(request, sent=sent):
            """仅替换网络，记录客户端真实序列化的请求。"""
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 0, "data": "Java context receipt"})

        client = client_class(base_url="http://java.invalid", token="test", transport=httpx.MockTransport(respond), dry_run=False)
        name = "SwapClientHttpx" if product == "swap" else "OptionClientHttpx"
        monkeypatch.setattr(module, name, lambda client=client: client)
        kwargs = {"close_order_req_vo": {}} if product == "close" else {"order_list": []}
        await getattr(module, f"call_{product}_backend")(_state(), intent=intent, **kwargs)
        assert len(sent) == 1
        payload = sent[0]
        assert payload["conversationId"] == "conv-1"
        assert payload["messageId"] == 20260917000042
        assert payload["messageContent"] == "腾讯 1000 股\n订单 H-1"
        assert payload["rawContent"] == "腾讯 1000 股" and payload["quoteContent"] == "订单 H-1"
        assert payload["operatorUserId"] == "op1" and payload["roomId"] == "r1" and payload["userId"] == "u1"
        assert "tickers" not in payload and "place_params" not in payload
