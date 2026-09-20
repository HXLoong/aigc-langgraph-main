"""Read failures must reach RetryPolicy instead of masquerading as zero matches."""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.graph.retry import add_io_node, io_node
from app.graph.state import AgentState
from app.subgraphs.ticker import resolver, tools


async def test_goats_transport_failure_is_not_a_valid_empty_result():
    client = MagicMock()
    client.search_securities_instrument = AsyncMock(side_effect=httpx.ConnectError("offline"))
    with pytest.raises(httpx.ConnectError):
        await resolver._search_goats(client, [{"keyword": "600000.SH", "isFull": True}])


async def test_llm_transport_failure_is_visible_to_the_graph(monkeypatch):
    model = MagicMock()
    invoke = AsyncMock(side_effect=httpx.ConnectError("offline"))
    model.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr(tools, "get_qwen_standard", lambda: model)
    with pytest.raises(httpx.ConnectError):
        await tools._call_ticker_llm(tools.INFER_CODE_SPEC, "600000.SH")
    assert invoke.await_count == 1, "transport retries belong to the graph, not nested helpers"


async def test_resolver_facade_does_not_hide_exhausted_failures(monkeypatch):
    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=httpx.ConnectError("exhausted"))
    monkeypatch.setattr("app.subgraphs.ticker.graph.get_ticker_graph", lambda: graph)
    with pytest.raises(httpx.ConnectError):
        await resolver.resolve_ticker_full("600000.SH")


async def test_schema_failure_is_retried_by_graph_once():
    attempts = []

    @io_node
    async def read(state):
        attempts.append(1)
        if len(attempts) == 1:
            raise OutputParserException("invalid schema")
        return {"reply_text": "valid structured output"}

    graph = StateGraph(AgentState)
    add_io_node(graph, "read", read, max_attempts=2, initial_interval=.001)
    graph.add_edge(START, "read")
    graph.add_edge("read", END)
    result = await graph.compile().ainvoke({})
    assert result.get("reply_text") == "valid structured output"
    assert len(attempts) == 2


async def test_missing_structured_tool_result_is_not_zero_matches(monkeypatch):
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=None)
    monkeypatch.setattr(tools, "get_qwen_standard", lambda: model)
    with pytest.raises(ValidationError):
        await tools._call_ticker_llm(tools.INFER_CODE_SPEC, "甲证券")
