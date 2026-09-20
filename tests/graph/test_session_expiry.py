"""过期会话清空旧交易上下文，本轮只返回确定性过期提示。"""
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.graph.state import Message


async def test_expired_turn_clears_memory_and_skips_business_nodes(monkeypatch):
    entry = importlib.import_module("app.nodes.ingest")
    main = importlib.import_module("app.graph.main")
    monkeypatch.setattr(entry, "get_settings", lambda: SimpleNamespace(
        conversation_idle_timeout_seconds=1800,
    ), raising=False)
    monkeypatch.setattr(entry, "time", lambda: 2000, raising=False)
    business = AsyncMock(side_effect=AssertionError("expired turn must not execute"))
    monkeypatch.setattr(main, "pre_route", business)
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    result = await main.build_main_graph().ainvoke({
        "raw_text": "确认下单", "last_activity_at": 100,
        "product_type": "option", "last_confirmed_params": {"order_ids": ["Q-old"]},
        "history_messages": [Message(role="assistant", content="旧订单")],
    })
    assert result["session_status"] == "expired"
    assert "会话已过期" in result["reply_text"]
    assert result["last_confirmed_params"] is None
    assert all(message.content != "旧订单" for message in result["history_messages"])
    business.assert_not_called()


async def test_fresh_turn_preserves_memory_and_refreshes_activity(monkeypatch):
    entry = importlib.import_module("app.nodes.ingest")
    monkeypatch.setattr(entry, "get_settings", lambda: SimpleNamespace(
        conversation_idle_timeout_seconds=1800,
    ), raising=False)
    monkeypatch.setattr(entry, "time", lambda: 2000, raising=False)
    update = await entry.ingest({"last_activity_at": 1900, "session_status": "expired"})
    assert update["session_status"] == "active"
    assert update["last_activity_at"] == 2000
    assert "last_confirmed_params" not in update


async def test_legacy_checkpoint_without_activity_is_started_without_expiring():
    entry = importlib.import_module("app.nodes.ingest")
    update = await entry.ingest({"history_messages": [Message(role="user", content="历史") ]})
    assert update["session_status"] == "active"
    assert update["last_activity_at"] > 0
    assert "history_messages" not in update
