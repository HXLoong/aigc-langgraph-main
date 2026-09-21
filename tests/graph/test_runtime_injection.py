"""Decorators preserve LangGraph's config/runtime injection and cancellation."""
import asyncio
from dataclasses import dataclass

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.graph.safe_node import safe_node
from app.graph.state import AgentState


@dataclass
class Context:
    tenant: str


async def test_safe_node_preserves_config_and_runtime_in_compiled_graph():
    @safe_node
    async def reader(state: AgentState, config: RunnableConfig, runtime: Runtime[Context]):
        return {"reply_text": runtime.context.tenant + ":" + config["configurable"]["thread_id"]}

    graph = StateGraph(AgentState, context_schema=Context)
    graph.add_node("reader", reader)
    graph.add_edge(START, "reader")
    graph.add_edge("reader", END)
    result = await graph.compile().ainvoke({}, {"configurable": {"thread_id": "thread"}},
                                          context=Context(tenant="local"))
    assert result["reply_text"] == "local:thread"
    assert not result.get("error")


async def test_cancellation_is_never_converted_into_a_successful_node_result():
    @safe_node
    async def cancelled(state):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await cancelled({})
