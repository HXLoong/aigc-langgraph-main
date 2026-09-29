"""option 子图编译 + 端到端测试（mock LLM）。"""
from __future__ import annotations

import pytest

from app.subgraphs.option import build_option_graph


def test_option_graph_compiles() -> None:
    graph = build_option_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_option_graph_routes_unknown_intent_to_option_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent → option_unknown 兜底（option 子图 6/6 真节点全到位）。"""
    from tests.joint_support import instruction_data
    graph = build_option_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "你好啊",
            "parsed_instruction": instruction_data("option", "unknown_intent", "你好啊"),
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
