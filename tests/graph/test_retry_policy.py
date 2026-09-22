"""IO 节点 RetryPolicy + @safe_node 分工（ADR 0024 D3）。

- 只读 IO 节点（LLM / 后端查询）用 @io_node：可重试异常穿透到 LangGraph RetryPolicy，
  重试耗尽由节点级 error_handler 落 state['error']；
- 写类节点（下单 / 撤单 / 确认 / 平仓）保持 @safe_node：绝不自动重试（金融正确性）。
"""
from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import END, START, StateGraph

from app.graph.retry import IO_RETRYABLE, add_io_node, io_node, is_retryable
from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ErrorInfo
from app.observability import metrics
from app.tools.exceptions import BackendUnreachableError, EmptyBackendResultError


@pytest.fixture(autouse=True)
def _reset_metrics() -> Any:
    metrics.get_collector().reset()
    yield
    metrics.get_collector().reset()


def test_retryable_set_is_transient_only() -> None:
    import httpx
    import openai

    assert is_retryable(BackendUnreachableError("swap", "timeout"))
    assert is_retryable(httpx.ConnectError("refused"))
    assert is_retryable(openai.APITimeoutError(request=httpx.Request("POST", "http://llm")))
    assert not is_retryable(EmptyBackendResultError("swap", 0))
    assert not is_retryable(ValueError("bad json"))
    assert BackendUnreachableError in IO_RETRYABLE


@pytest.mark.asyncio
async def test_io_node_reraises_retryable_and_counts_retry_metric() -> None:
    @io_node
    async def reader(state: AgentState) -> dict[str, Any]:
        raise BackendUnreachableError("swap", "timeout")

    with pytest.raises(BackendUnreachableError):
        await reader({})  # type: ignore[arg-type]
    assert metrics.get_collector().get_counter(
        metrics.METRIC_NODE_TOTAL, {"node": "reader", "status": "retry"}
    ) == 1


@pytest.mark.asyncio
async def test_io_node_swallows_non_retryable_like_safe_node() -> None:
    @io_node
    async def reader(state: AgentState) -> dict[str, Any]:
        raise EmptyBackendResultError("swap", 0)

    update = await reader({})  # type: ignore[arg-type]
    assert isinstance(update["error"], ErrorInfo) and update["error"].type == "EmptyBackendResultError"


@pytest.mark.asyncio
async def test_plain_safe_node_still_swallows_retryable() -> None:
    """写类节点保持旧语义：超时也不重试，直接落 error 交 render 出"系统暂时不可用"。"""
    @safe_node
    async def writer(state: AgentState) -> dict[str, Any]:
        raise BackendUnreachableError("swap", "timeout")

    update = await writer({})  # type: ignore[arg-type]
    assert update["error"].type == "BackendUnreachableError"


def _graph(fn: Any) -> Any:
    g = StateGraph(AgentState)
    add_io_node(g, "io", fn, max_attempts=3, initial_interval=0.001)
    g.add_edge(START, "io")
    g.add_edge("io", END)
    return g.compile()


@pytest.mark.asyncio
async def test_graph_retries_transient_failure_then_succeeds() -> None:
    calls = {"n": 0}

    @io_node
    async def flaky(state: AgentState) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise BackendUnreachableError("swap", "timeout")
        return {"intent": "query_order_status"}

    final = await _graph(flaky).ainvoke({"raw_text": "x"})
    assert calls["n"] == 3
    assert final.get("error") is None
    assert final["intent"] == "query_order_status"


@pytest.mark.asyncio
async def test_graph_retry_exhausted_lands_in_state_error_with_trace() -> None:
    calls = {"n": 0}

    @io_node
    async def dead(state: AgentState) -> dict[str, Any]:
        calls["n"] += 1
        raise BackendUnreachableError("swap", "connect_error")

    final = await _graph(dead).ainvoke({"raw_text": "x"})
    assert calls["n"] == 3, "max_attempts=3 → 恰好 3 次"
    err = final["error"]
    assert isinstance(err, ErrorInfo)
    assert (err.node, err.type) == ("io", "BackendUnreachableError")
    assert "connect_error" in err.message
    decisions = [(e.node, e.decision) for e in final["trace"]]
    assert ("io", "error:retry_exhausted") in decisions


@pytest.mark.asyncio
async def test_graph_non_retryable_runs_once() -> None:
    calls = {"n": 0}

    @io_node
    async def bad(state: AgentState) -> dict[str, Any]:
        calls["n"] += 1
        raise EmptyBackendResultError("swap", 0)

    final = await _graph(bad).ainvoke({"raw_text": "x"})
    assert calls["n"] == 1
    assert final["error"].type == "EmptyBackendResultError"


def test_add_io_node_rejects_function_without_io_node_decorator() -> None:
    @safe_node
    async def writer(state: AgentState) -> dict[str, Any]:
        return {}

    g = StateGraph(AgentState)
    with pytest.raises(TypeError, match="@io_node"):
        add_io_node(g, "writer", writer)


#: 只读 IO 节点：必须带 RetryPolicy + error_handler
READ_NODES: dict[str, set[str]] = {
    "main": {"intent_route", "existing_command_query", "plan_instructions"},
    "swap": {
        "swap_intent", "swap_select_counterparty", "swap_select_ticker",
        "swap_recognize_fresh_counterparty",
        "swap_query_order", "swap_image_order", "swap_excel_order",
    },
    "swap_place": {"swap_extract_candidates"},
    "option": {"option_intent", "option_extract_query"},
    "inquiry": {"inquiry_fast_parse", "inquiry_extract"},
    "close": {"close_intent", "close_holding_query", "close_query_status"},
    "place_close": {"place_close_fetch_orders", "place_close_extract"},
}
#: 写类节点：绝不自动重试
WRITE_NODES: dict[str, set[str]] = {
    "main": {"quick_inquiry", "persist_intent", "persist"},
    "swap": {"swap_place_order_submit", "swap_confirm", "swap_cancel"},
    "option": {
        "option_extract_inquiry", "option_extract_place", "option_extract_confirm_place",
        "option_extract_cancel", "option_extract_cancel_place", "option_extract_confirm_cancel",
    },
    "inquiry": {"inquiry_fast_submit", "inquiry_submit"},
    "close": {"close_confirm_close", "close_cancel_close", "close_confirm_cancel"},
    "place_close": {"place_close_submit"},
}
#: 纯计算 / 编排 / 原生嵌入子图节点：无 IO，不挂 RetryPolicy 也不算写类
PURE_NODES: dict[str, set[str]] = {
    "main": {
        "ingest", "entry_route", "pre_route", "fallback", "render",
        "remember_confirmed_params", "record_history",
        "swap", "option", "option_close", "instructions",
    },
    "swap": {"swap_place_order", "swap_apply_picks", "swap_unknown"},
    "swap_place": {"swap_normalize", "swap_place_result"},
    "option": {"option_unknown"},
    "inquiry": {"inquiry_normalize"},
    "close": {"close_place_close", "close_unknown"},
    "place_close": {
        "place_close_parse", "place_close_normalize", "place_close_validate", "place_close_reject",
    },
}


def _builders() -> dict[str, Any]:
    from app.graph.main import build_main_graph
    from app.subgraphs.close.graph import build_close_graph
    from app.subgraphs.close.place_close import build_place_close_graph
    from app.subgraphs.option.extract_inquiry import build_inquiry_graph
    from app.subgraphs.option.graph import build_option_graph
    from app.subgraphs.swap.graph import build_swap_graph
    from app.subgraphs.swap.place_order import build_place_graph

    return {
        "main": build_main_graph().builder,
        "swap": build_swap_graph().builder,
        "swap_place": build_place_graph().builder,
        "option": build_option_graph().builder,
        "inquiry": build_inquiry_graph().builder,
        "close": build_close_graph().builder,
        "place_close": build_place_close_graph().builder,
    }


def test_real_graphs_retry_reads_and_never_writes() -> None:
    builders = _builders()
    for graph_name, names in READ_NODES.items():
        for name in names:
            spec = builders[graph_name].nodes[name]
            assert spec.retry_policy is not None, f"{graph_name}.{name} 缺 RetryPolicy"
            assert spec.error_handler_node, f"{graph_name}.{name} 缺 error_handler"
    for graph_name, names in WRITE_NODES.items():
        for name in names:
            spec = builders[graph_name].nodes[name]
            assert spec.retry_policy is None, f"{graph_name}.{name} 是写类节点，不得自动重试"


def test_every_graph_node_is_classified_read_write_or_pure() -> None:
    """完整性守护：新增节点必须显式归类，否则写类节点被误挂 RetryPolicy（超时重发下单）不会被发现。"""
    for graph_name, builder in _builders().items():
        actual = {name for name, spec in builder.nodes.items() if not spec.is_error_handler}
        expected = (
            READ_NODES.get(graph_name, set())
            | WRITE_NODES.get(graph_name, set())
            | PURE_NODES.get(graph_name, set())
        )
        assert actual == expected, (
            f"{graph_name}: 未归类 {sorted(actual - expected)} / 已不存在 {sorted(expected - actual)}"
        )
        overlap = READ_NODES.get(graph_name, set()) & WRITE_NODES.get(graph_name, set())
        assert not overlap, f"{graph_name}: 同时归为读写 {sorted(overlap)}"
    for graph_name, names in PURE_NODES.items():
        for name in names:
            spec = _builders()[graph_name].nodes[name]
            assert spec.retry_policy is None, f"{graph_name}.{name} 是纯计算节点，不应挂 RetryPolicy"


def test_inquiry_has_no_local_ticker_stages():
    from app.subgraphs.option.extract_inquiry import build_inquiry_graph
    graph = build_inquiry_graph().builder
    for name in ("inquiry_precheck", "inquiry_resolve"):
        assert name not in graph.nodes
