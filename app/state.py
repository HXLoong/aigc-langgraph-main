"""兼容层：重定向到 M2 新位置 app.graph.state。"""
from app.graph.state import AgentState, Message, TickerCandidate  # noqa: F401

# M2 用 AgentState TypedDict + 直接构造，不再有 WechatInput/make_initial_state
# 给 eval 提供兼容包装
from typing import Any

class WechatInput(dict):
    """兼容 M1 的 WechatInput TypedDict。"""
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


def make_initial_state(wechat_input: dict) -> dict[str, Any]:
    """兼容 M1 的 make_initial_state。M2 直接构造 AgentState dict。"""
    state: dict[str, Any] = {
        "raw_text": wechat_input.get("raw_content", ""),
        "quote_content": wechat_input.get("quote_content"),
        "conversation_id": wechat_input.get("conversation_id", ""),
        "message_id": wechat_input.get("message_id", ""),
        "room_id": wechat_input.get("room_id", ""),
        "user_id": wechat_input.get("user_id", ""),
        "guid": wechat_input.get("guid", ""),
        "attachments": wechat_input.get("attachments", []),
        "bot_name_list": [],
        "history_messages": [],
        "conversation_orders": [],
        "counterparty_list": [],
        "product_type": "unknown",
        "intent": None,
        "fast_query": False,
        "at_bot": False,
        "place_params": {},
        "cancel_params": {},
        "close_params": {},
        "order_list": [],
        "order_ids": [],
        "api_code": None,
        "api_result": None,
        "error": None,
        "reply_text": None,
        "trace": [],
    }
    return state
