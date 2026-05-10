"""option 子图编译 + 端到端测试（mock LLM）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import build_option_graph
from app.subgraphs.option import intent as intent_module
from app.subgraphs.option.models import OptionIntentOutput


def _patch_llm(monkeypatch: pytest.MonkeyPatch, return_type: str) -> None:
    fake_output = OptionIntentOutput(type=return_type)  # type: ignore[arg-type]
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=fake_output)
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
async def test_option_graph_runs_intent_then_todo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """骨架阶段：intent → todo 路径完整跑通。"""
    _patch_llm(monkeypatch, "new_inquiry")
    graph = build_option_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "期权询价 腾讯控股 1个月",
            "conversation_id": "test-1",
            "user_id": "u1",
            "room_id": "r1",
            "message_id": 1,
            "message_content": "期权询价 腾讯控股 1个月",
        }
    )
    assert final.get("intent") == "new_inquiry"
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_intent" in trace_nodes
    assert "option_todo" in trace_nodes
    todo_entry = next(e for e in final["trace"] if e.node == "option_todo")
    assert "not_implemented_yet" in todo_entry.decision
    assert "new_inquiry" in todo_entry.decision
