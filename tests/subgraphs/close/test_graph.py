"""close 子图编译 + 端到端测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.models import CloseIntentOutput


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> None:
    fake_output = CloseIntentOutput(type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        intent_module, "get_qwen_structured", lambda: fake_base_llm
    )


def test_close_graph_compiles() -> None:
    graph = build_close_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_close_graph_runs_intent_then_todo_for_unimplemented_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未实现意图（close_order_cancel_confirm 当前还没真节点）→ 走 todo。"""
    _patch_llm(monkeypatch, "close_order_cancel_confirm")
    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "确认撤销平仓 CO-20260304-0001",
            "conversation_id": "test-1",
            "user_id": "u1",
            "room_id": "r1",
            "message_id": 1,
            "message_content": "确认撤销平仓 CO-20260304-0001",
        }
    )
    assert final.get("intent") == "close_order_cancel_confirm"
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_intent" in trace_nodes
    assert "close_todo" in trace_nodes
    assert "close_holding_query" not in trace_nodes
    assert "close_confirm_close" not in trace_nodes
    todo_entry = next(e for e in final["trace"] if e.node == "close_todo")
    assert "close_order_cancel_confirm" in todo_entry.decision
