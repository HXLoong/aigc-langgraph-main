"""重试耗尽仍须完成原图的错误路由、并行汇合和审计收尾（#223）。"""
from __future__ import annotations

from importlib import import_module
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph.retry import add_io_node, io_node
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, TraceEntry


@pytest.fixture
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(update={
        "node_retry_max_attempts": 2, "node_retry_initial_interval_seconds": 0,
    })
    monkeypatch.setattr("app.graph.retry.get_settings", lambda: settings)
    monkeypatch.setattr("langgraph.pregel._retry.random.uniform", lambda *_: 0)


def failing_node(name: str, calls: list[str]) -> Any:
    async def fail(state: AgentState) -> dict[str, Any]:
        calls.append(name)
        raise TimeoutError(f"{name} unavailable")

    fail.__name__ = name
    return io_node(fail)


@pytest.mark.parametrize("node_name", ["intent_route", "existing_command_query"])
async def test_main_retry_exhaustion_reaches_reply_history_and_audit(
    monkeypatch: pytest.MonkeyPatch, fast_retries: None, node_name: str,
) -> None:
    from app.graph import main

    @safe_node
    async def ingest(state: AgentState) -> dict[str, Any]:
        return {}

    calls: list[str] = []
    audit = AsyncMock(return_value={"trace": [TraceEntry(node="persist")]})
    monkeypatch.setattr(main, "ingest", ingest)
    monkeypatch.setattr(main, "pre_route", AsyncMock(return_value={}))
    monkeypatch.setattr(main, node_name, failing_node(node_name, calls))
    monkeypatch.setattr(main, "persist", audit)
    monkeypatch.setattr(main, "_route_entry", lambda _: (
        "existing_command_query" if node_name == "existing_command_query" else "pre_route"
    ))
    result = await main.build_main_graph().ainvoke({
        "raw_text": "查询订单", "conversation_id": "retry-test", "message_id": 123,
    })
    names = [entry.node for entry in result["trace"]]
    assert calls == [node_name, node_name]
    assert result["error"].node == node_name
    assert result.get("reply_text"), "主图失败必须生成用户回复"
    assert names.count("render") == names.count("record_history") == names.count("persist") == 1
    assert any(entry.decision == "error:retry_exhausted" for entry in result["trace"])
    audit.assert_awaited_once()


@pytest.mark.parametrize("product", ["swap", "option", "close"])
async def test_subgraph_retry_exhaustion_reaches_its_fallback(
    monkeypatch: pytest.MonkeyPatch, fast_retries: None, product: str,
) -> None:
    module = import_module(f"app.subgraphs.{product}.graph")
    name = f"{product}_intent"
    calls: list[str] = []
    monkeypatch.setattr(module, name, failing_node(name, calls))
    result = await getattr(module, f"build_{product}_graph")().ainvoke({"raw_text": "测试"})
    assert calls == [name, name]
    assert result["error"].node == name
    assert [entry.node for entry in result["trace"]] == [name, f"{product}_unknown"]


@pytest.mark.parametrize("failures", [set(), {"left"}, {"left", "right"}])
async def test_parallel_retry_exhaustion_merges_before_any_write(
    fast_retries: None, failures: set[str],
) -> None:
    calls: list[str] = []
    joined: list[bool] = []
    writes = AsyncMock(return_value={})

    @io_node
    async def success(state: AgentState) -> dict[str, Any]:
        return {}

    async def join(state: AgentState) -> dict[str, Any]:
        joined.append(bool(state.get("error")))
        return {}

    graph = StateGraph(AgentState)
    for name in ("left", "right"):
        add_io_node(graph, name, failing_node(name, calls) if name in failures else success)
        graph.add_edge(START, name)
        graph.add_edge(name, "join")
    graph.add_node("join", join)
    graph.add_node("write", writes)
    graph.add_conditional_edges("join", lambda state: END if state.get("error") else "write")
    graph.add_edge("write", END)
    result = await graph.compile().ainvoke({})
    assert joined == [bool(failures)], "两个分支收敛后只执行一次汇合"
    if failures:
        error = result["error"]
        assert {error.node, *(cause.node for cause in error.causes)} == failures
        assert all(calls.count(name) == 2 for name in failures)
        writes.assert_not_awaited()
    else:
        writes.assert_awaited_once()


async def test_disabled_recovery_still_propagates_after_all_attempts(fast_retries: None) -> None:
    calls: list[str] = []
    graph = StateGraph(AgentState)
    add_io_node(graph, "private", failing_node("private", calls), with_error_handler=False)
    graph.add_edge(START, "private")
    graph.add_edge("private", END)
    with pytest.raises(TimeoutError, match="private unavailable"):
        await graph.compile().ainvoke({})
    assert calls == ["private", "private"]
