"""close 子图编译 + 端到端测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.models import CloseIntentOutput
from tests.intent_fixtures import intent_reply, mock_ainvoke


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> None:
    fake_output = intent_reply(CloseIntentOutput, type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = mock_ainvoke(fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        intent_module, "get_qwen_thinking", lambda: fake_base_llm
    )


def test_close_graph_compiles() -> None:
    graph = build_close_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_close_graph_routes_unknown_intent_to_close_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent → close_unknown 兜底（close 子图所有 6 个 close_order_* 真节点已到位）。"""
    _patch_llm(monkeypatch, "unknown_intent")
    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "你好啊",
            "conversation_id": "test-1",
            "user_id": "u1",
            "room_id": "r1",
            "message_id": 1,
            "message_content": "你好啊",
        }
    )
    assert final.get("intent") == "unknown_intent"
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_intent" in trace_nodes
    assert "close_unknown" in trace_nodes
    assert "close_holding_query" not in trace_nodes
    unknown_entry = next(e for e in final["trace"] if e.node == "close_unknown")
    assert "unhandled_intent=unknown_intent" in unknown_entry.decision
