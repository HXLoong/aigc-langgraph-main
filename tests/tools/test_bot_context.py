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


def test_backends_build_context_from_bot_context() -> None:
    from app.subgraphs.close import backend as close_backend
    from app.subgraphs.option import backend as option_backend
    from app.subgraphs.swap import backend as swap_backend

    state = _state()
    wire = BotContext.from_state(state).to_wire()
    assert option_backend._context(state) == wire
    assert swap_backend._context(state) == wire
    assert close_backend._context(state) == wire
    assert swap_backend._context({"raw_text": "x"})["operatorUserId"] == "", "swap 未填操作者透传空串"
