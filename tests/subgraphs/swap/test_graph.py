"""swap 子图编译 + 端到端测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import build_swap_graph
from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap.models import SwapIntentOutput


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> None:
    fake_output = SwapIntentOutput(type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        intent_module, "get_qwen_structured", lambda: fake_base_llm
    )


def test_swap_graph_compiles() -> None:
    """子图能编译，不抛异常。"""
    graph = build_swap_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_swap_graph_routes_unknown_intent_to_swap_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent → swap_unknown 兜底（swap 子图主路由 7/7 意图全到位）。"""
    _patch_llm(monkeypatch, "unknown_intent")
    graph = build_swap_graph()
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
    assert "swap_intent" in trace_nodes
    assert "swap_unknown" in trace_nodes
    assert "swap_place_order" not in trace_nodes
    unknown_entry = next(e for e in final["trace"] if e.node == "swap_unknown")
    assert "unhandled_intent=unknown_intent" in unknown_entry.decision
