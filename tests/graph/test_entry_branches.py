"""主图前置分流测试(DSL v2「判断快速询价」)。"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.nodes.fast_query as fq
from app.graph.main import _route_entry, build_main_graph
from app.tools.goats_agent_client import IGNORE_REPLY_SENTINEL


class TestRouteEntry:
    def test_fast_query_branch(self):
        assert _route_entry({"fast_query": "1"}) == "quick_inquiry"

    def test_existing_command_branch(self):
        assert (
            _route_entry({"existing_command": "1", "at_bot": "0"})
            == "existing_command_query"
        )

    def test_at_bot_blocks_existing_command(self):
        assert _route_entry({"existing_command": "1", "at_bot": "1"}) == "pre_route"

    def test_default_goes_pre_route(self):
        assert _route_entry({"raw_text": "互换下单"}) == "pre_route"


class FakeAgentClient:
    async def parse_rfq_instrument(self, query, room_id, user_id):
        return {"code": 500, "errMsg": "快速询价暂不可用,请检查网络"}

    async def query_instruction(self, query, room_id, user_id):
        return {
            "code": 0,
            "errMsg": IGNORE_REPLY_SENTINEL,
            "api_data_result_obj": {"rows": []},
        }


@pytest.mark.asyncio
async def test_e2e_fast_query_skips_intent_route(monkeypatch):
    """fast_query=1 的请求不经过 pre_route/intent_route,直接快速询价链。"""
    monkeypatch.setattr(fq, "_make_agent_client", lambda: FakeAgentClient())
    graph = build_main_graph(InMemorySaver())
    final = await graph.ainvoke(
        {"raw_text": "参与型看涨 茅台 1M", "fast_query": "1", "conversation_id": "t-fq"},
        config={"configurable": {"thread_id": "t-fq"}},
    )
    nodes = [e.node for e in final["trace"]]
    assert "quick_inquiry" in nodes
    assert "intent_route" not in nodes
    assert "persist_intent" not in nodes
    assert final["reply_text"] == "快速询价暂不可用,请检查网络"


@pytest.mark.asyncio
async def test_e2e_existing_command_silent_sentinel(monkeypatch):
    monkeypatch.setattr(fq, "_make_agent_client", lambda: FakeAgentClient())
    graph = build_main_graph(InMemorySaver())
    final = await graph.ainvoke(
        {
            "raw_text": "#TRS #当日委托",
            "existing_command": "1",
            "at_bot": "0",
            "conversation_id": "t-ec",
        },
        config={"configurable": {"thread_id": "t-ec"}},
    )
    assert final["reply_text"] == IGNORE_REPLY_SENTINEL
    assert "intent_route" not in [e.node for e in final["trace"]]
    assert "persist_intent" not in [e.node for e in final["trace"]]


@pytest.mark.asyncio
async def test_e2e_pre_route_populates_counterparties():
    graph = build_main_graph(InMemorySaver())
    final = await graph.ainvoke(
        {
            "raw_text": "查一下互换订单",
            "conversation_id": "t-pr",
            "swap_counterparties_raw": '[{"ctptyId":"C1","shortName":"中信","longName":"中信证券","sort":"A"}]',
        },
        config={"configurable": {"thread_id": "t-pr"}},
    )
    assert final.get("swap_counterparties") == [
        {"ctptyId": "C1", "shortName": "中信", "longName": "中信证券", "sort": "A"}
    ]
    assert "pre_route" in [e.node for e in final["trace"]]
