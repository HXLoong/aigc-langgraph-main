"""close 子图路由扩展测试 · 验证新增 confirm_close / cancel_close 路径。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.models import CloseIntentOutput


def _patch_close_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """close/backend.py 调用的 OptionClientHttpx.operate 不打真网络。"""

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        return {"code": 0, "msg": "ok", "data": "mock-backend-result"}

    monkeypatch.setattr(
        "app.tools.option_client.OptionClientHttpx.operate", _fake_operate
    )


def _forbid_deterministic_llms(monkeypatch: pytest.MonkeyPatch) -> None:
    """confirm_close / cancel_close 已去 LLM 化：工厂若被调用即报错。"""

    def _forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("去 LLM 化节点不应调用 LLM")

    for target in (
        "app.subgraphs.close.confirm_close.get_qwen_thinking",
        "app.subgraphs.close.cancel_close.get_qwen_thinking",
    ):
        monkeypatch.setattr(target, _forbid, raising=False)


def _patch_intent(monkeypatch: pytest.MonkeyPatch, intent_type: str) -> None:
    """close.intent 分类结果固定为 intent_type。"""
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=CloseIntentOutput(type=intent_type))
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_base)


@pytest.mark.asyncio
async def test_close_order_confirm_routes_to_confirm_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_order_confirm → close_confirm_close 节点。"""
    _patch_intent(monkeypatch, "close_order_confirm")
    _forbid_deterministic_llms(monkeypatch)
    _patch_close_backend(monkeypatch)

    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "确认平仓 CO-20260304-ABCD",
            "quote_content": "订单 CO-20260304-ABCD",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "确认平仓 CO-20260304-ABCD",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_intent" in trace_nodes
    assert "close_confirm_close" in trace_nodes
    assert "close_todo" not in trace_nodes
    assert final.get("intent") == "close_order_confirm"
    assert final.get("confirm", {}).get("action") == "close"


@pytest.mark.asyncio
async def test_close_order_cancel_request_routes_to_cancel_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_order_cancel_request → close_cancel_close 节点。"""
    _patch_intent(monkeypatch, "close_order_cancel_request")
    _forbid_deterministic_llms(monkeypatch)
    _patch_close_backend(monkeypatch)

    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "撤销平仓单 CO-20260304-A1B2C3D4",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "撤销平仓单 CO-20260304-A1B2C3D4",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_cancel_close" in trace_nodes
    assert "close_todo" not in trace_nodes
    assert final.get("cancel_params", {}).get("cancelOrderNoList") == [
        "CO-20260304-A1B2C3D4"
    ]


@pytest.mark.asyncio
async def test_unmapped_intent_still_routes_to_todo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """剩余未实现意图（如 close_order_cancel_confirm / order_query）走 todo。"""
    _patch_intent(monkeypatch, "unknown_intent")
    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "你好啊",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_unknown" in trace_nodes
    assert "close_confirm_close" not in trace_nodes
    assert "close_cancel_close" not in trace_nodes
