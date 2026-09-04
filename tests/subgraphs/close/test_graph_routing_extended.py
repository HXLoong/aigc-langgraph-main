"""close 子图路由扩展测试 · 验证新增 confirm_close / cancel_close 路径。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import cancel_close as cancel_module
from app.subgraphs.close import confirm_close as confirm_module
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.models import (
    CancelCloseParams,
    CloseIntentOutput,
    ConfirmCloseParams,
)


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    value: object,
    fn: str = "get_qwen_thinking",
) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=value)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(module, fn, lambda: fake_base)
    if hasattr(module, "call_option_backend"):
        monkeypatch.setattr(
            module,
            "call_option_backend",
            AsyncMock(
                return_value={"api_code": 0, "api_result": "backend reply"}
            ),
        )


@pytest.mark.asyncio
async def test_close_order_confirm_routes_to_confirm_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_order_confirm → close_confirm_close 节点。"""
    _patch(monkeypatch, intent_module, CloseIntentOutput(type="close_order_confirm"))
    _patch(
        monkeypatch,
        confirm_module,
        ConfirmCloseParams(confirmOrderNoList=["CO-20260304-ABCD"]),
        fn="get_qwen_thinking",
    )

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
    _patch(
        monkeypatch,
        intent_module,
        CloseIntentOutput(type="close_order_cancel_request"),
    )
    _patch(
        monkeypatch,
        cancel_module,
        CancelCloseParams(cancelOrderNoList=["CO-20260304-XYZ"]),
    )

    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "撤销平仓单 CO-20260304-XYZ",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "撤销平仓单 CO-20260304-XYZ",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_cancel_close" in trace_nodes
    assert "close_todo" not in trace_nodes
    assert final.get("cancel_params", {}).get("cancelOrderNoList") == [
        "CO-20260304-XYZ"
    ]


@pytest.mark.asyncio
async def test_unmapped_intent_still_routes_to_todo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """剩余未实现意图（如 close_order_cancel_confirm / order_query）走 todo。"""
    _patch(
        monkeypatch,
        intent_module,
        CloseIntentOutput(type="unknown_intent"),
    )
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
