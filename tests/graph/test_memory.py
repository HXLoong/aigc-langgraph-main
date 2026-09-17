"""ConversationMemory 读取 + 跨轮持久化 + 主图接线（ADR 0024 D4）。"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.memory import memory_order_ids
from app.graph.state import AgentState
from app.nodes.ingest import ingest

_MEM = {"product_type": "swap", "intent": "place_order_request", "expected_action": "place",
        "order_ids": ["H-20260917-0000000001"], "message_id": 1}


def test_memory_order_ids_only_for_matching_product() -> None:
    assert memory_order_ids({"last_confirmed_params": _MEM}, "swap") == ["H-20260917-0000000001"]
    assert memory_order_ids({"last_confirmed_params": _MEM}, "option") == []
    assert memory_order_ids({}, "swap") == []
    assert memory_order_ids({"last_confirmed_params": {"product_type": "swap"}}, "swap") == []


@pytest.mark.asyncio
async def test_memory_survives_next_turn_ingest_on_checkpoint() -> None:
    async def writer(state: AgentState) -> dict:
        return {"last_confirmed_params": _MEM} if state.get("raw_text") == "下单" else {}

    g = StateGraph(AgentState)
    g.add_node("ingest", ingest)
    g.add_node("writer", writer)
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "writer")
    g.add_edge("writer", END)
    graph = g.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    await graph.ainvoke({"raw_text": "下单", "conversation_id": "t1"}, config=cfg)
    final = await graph.ainvoke({"raw_text": "确认下单", "conversation_id": "t1"}, config=cfg)
    assert final["last_confirmed_params"] == _MEM
    assert final.get("place_params") is None, "业务对象仍是 per-turn"


def test_main_graph_remembers_after_render_before_history() -> None:
    from app.graph.main import build_main_graph

    builder = build_main_graph().builder
    assert "remember_confirmed_params" in builder.nodes
    edges = {(a, b) for a, b in builder.edges}
    assert ("render", "remember_confirmed_params") in edges
    assert ("remember_confirmed_params", "record_history") in edges
