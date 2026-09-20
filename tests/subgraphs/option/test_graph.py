"""option 子图编译 + 端到端测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.subgraphs.option import build_option_graph
from app.subgraphs.option import intent as intent_module
from app.subgraphs.option.models import OptionIntentOutput
from tests.intent_fixtures import intent_reply, mock_ainvoke


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> None:
    fake_output = intent_reply(OptionIntentOutput, type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = mock_ainvoke(fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        intent_module, "get_qwen_structured", lambda: fake_base_llm
    )


def test_option_graph_compiles() -> None:
    graph = build_option_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_option_graph_routes_unknown_intent_to_option_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent → option_unknown 兜底（option 子图 6/6 真节点全到位）。"""
    _patch_llm(monkeypatch, "unknown_intent")
    graph = build_option_graph()
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
    assert "option_intent" in trace_nodes
    assert "option_unknown" in trace_nodes
    assert "option_extract_inquiry" not in trace_nodes
    unknown_entry = next(e for e in final["trace"] if e.node == "option_unknown")
    assert "unhandled_intent=unknown_intent" in unknown_entry.decision
