"""用真实 SDK 和内存 HTTP 边界验证跨进程关联，不访问外部服务。"""
from __future__ import annotations

import asyncio
import json
from contextvars import Context
from typing import Any, TypedDict
from uuid import uuid4

import httpx
import pytest
from langfuse import Langfuse
from langgraph.graph import END, START, StateGraph
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import get_settings
from app.observability import tracing
from harness import langfuse_client
from harness.golden import GoldenCase
from harness.multi_turn import run_case_multi


class _State(TypedDict, total=False):
    """合成图仅返回一个确定性结果。"""

    ok: bool


@pytest.fixture
def memory_client(monkeypatch: pytest.MonkeyPatch):
    """让两端共享测试项目，所有 Observation 只写内存 exporter。"""
    from opentelemetry import context as otel_context

    token = otel_context.attach(otel_context.Context())
    exporter = InMemorySpanExporter()
    key = "pk-lf-regression-" + uuid4().hex
    client = Langfuse(public_key=key, secret_key="synthetic-key",
                      base_url="http://langfuse.invalid", tracer_provider=TracerProvider(),
                      span_exporter=exporter, tracing_enabled=True)
    settings = get_settings().model_copy(update={
        "enable_langfuse": True, "langfuse_public_key": key,
        "langfuse_secret_key": "synthetic-key", "trust_inbound_traceparent": True,
    })
    # 只替换配置与出口；回调、图调度及上下文传播使用生产实现。
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    monkeypatch.setattr(tracing, "_langfuse_client", client)
    monkeypatch.setattr(client, "get_trace_url", lambda **kw: "http://langfuse.invalid/trace/" + kw["trace_id"])
    monkeypatch.setattr(langfuse_client, "_client", client, raising=False)
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    try:
        yield client, exporter
    finally:
        client.shutdown()
        otel_context.detach(token)


async def _server(request: httpx.Request) -> httpx.Response:
    """独立 Context 模拟服务端进程，唯一父关联来源是 HTTP 请求头。"""
    body = json.loads(request.content)
    session_id = body["conversation_id"]
    trace = await tracing.attach_request_trace(
        request_trace_id=uuid4().hex, traceparent=request.headers.get("traceparent"),
    )

    async def node(state: _State) -> dict[str, bool]:
        """让并发请求交错，以暴露上下文串用。"""
        await asyncio.sleep(0)
        return {"ok": True}

    graph = StateGraph(_State)
    graph.add_node("synthetic_node", node)
    graph.add_edge(START, "synthetic_node")
    graph.add_edge("synthetic_node", END)
    await graph.compile().ainvoke({}, config={
        "callbacks": [trace.handler], "metadata": {"langfuse_session_id": session_id},
    })
    return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {
        "reply_text": "synthetic reply", "langfuse_trace_id": trace.langfuse_trace_id,
        "session_id": session_id,
    }}})


async def test_concurrent_cases_share_http_parent_and_session_per_case(memory_client: Any) -> None:
    """每个两轮用例只有一棵树，两个并发用例的树和 Session 彼此隔离。"""
    client, exporter = memory_client
    headers: list[str | None] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        """模拟跨进程；禁止依赖调用方 ContextVar 的隐式继承。"""
        headers.append(request.headers.get("traceparent"))
        return await asyncio.create_task(_server(request), context=Context())

    cases = [GoldenCase(id=f"case-{i}", category="test", turns=[
        {"send_text": "one"}, {"send_text": "two", "quote_previous": True},
    ]) for i in range(2)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        results = await asyncio.gather(*(run_case_multi(
            case, base_url="http://localhost:8201", user_id="test-user", room_id="test-room",
            client=http,
        ) for case in cases))
    client.flush()

    # 1. HTTP 确实传递父上下文，且业务执行完整。
    assert len(headers) == 4 and all(headers), "HTTP 回归缺少 traceparent"
    assert all(len(result.turns) == 2 and result.failure is None for result in results)
    spans = exporter.get_finished_spans()
    assert len({span.context.trace_id for span in spans}) == 2

    # 2. 每棵树只有一个根，所有子节点都有同一 Session 和可解析的父节点。
    for result in results:
        rows = [span for span in spans if span.attributes.get("session.id") == result.conversation_id]
        assert rows and len([span for span in rows if span.parent is None]) == 1
        identities = {span.context.span_id for span in rows}
        assert all(span.parent is None or span.parent.span_id in identities for span in rows)
        assert {f"{span.context.trace_id:032x}" for span in rows} == {result.langfuse_trace_id}
        assert result.trace_status == "complete"


def test_report_retains_server_and_case_trace_identity() -> None:
    """离线报告可直接定位用例根和单轮服务端调用。"""
    from harness.cli import _report_case
    from harness.multi_turn import MultiTurnResult, _extract_turn

    case = GoldenCase(id="reported", category="test", turns=[{"send_text": "one"}])
    result = MultiTurnResult(case.id, "conversation", turns=[_extract_turn(1, case.turns[0], "", {
        "trace_id": "audit-id", "langfuse_trace_id": "case-trace",
        "observation_id": "server-span", "trace_url": "http://langfuse.invalid/t",
    })], langfuse_trace_id="case-trace", observation_id="case-span", trace_status="complete")
    report = _report_case(case, result, {})
    assert report.get("langfuse_trace_id") == "case-trace"
    assert report["turns"][0].get("trace_id") == "audit-id"
    assert report["turns"][0].get("observation_id") == "server-span"


async def test_node_http_execution_joins_parent_trace(memory_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """节点调试入口也必须接续父 Trace，且不把观测字段混入节点输出。"""
    from fastapi import FastAPI
    from langfuse import propagate_attributes

    from app.api.nodes import router
    from app.graph.state import AgentState
    from app.node_execution.executor import NodeExecutor
    from app.node_execution.registry import NodeRegistration

    client, exporter = memory_client

    async def target(state: AgentState) -> dict[str, str]:
        """只返回目标节点更新，验证 API 仍保持隔离执行契约。"""
        return {"reply_text": "done"}

    app = FastAPI()
    app.include_router(router)
    app.state.node_executor = NodeExecutor([NodeRegistration(
        "main", "synthetic_target", target, input_fields=("conversation_id",),
    )])
    with (client.start_as_current_observation(name="node_case") as root,
          propagate_attributes(session_id="node-session")):
        async def send() -> httpx.Response:
            """清空 Context 后仅通过 HTTP 头建立父关系。"""
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                return await http.post("/v1/nodes/run", json={
                    "product": "main", "node": "synthetic_target", "state": {"conversation_id": "node-session"},
                }, headers={"traceparent": f"00-{root.trace_id}-{root.id}-01"})
        response = await asyncio.create_task(send(), context=Context())
    client.flush()
    assert response.status_code == 200 and response.json()["output"] == {"reply_text": "done"}
    assert response.json()["tracing"].get("observation_id"), "缺少服务端根 Observation ID"
    spans = exporter.get_finished_spans()
    assert len(spans) >= 3, "节点调试未产生服务端 Observation"
    assert {f"{span.context.trace_id:032x}" for span in spans} == {root.trace_id}
    assert all(span.attributes.get("session.id") == "node-session" for span in spans)


async def test_existing_experiment_root_receives_case_session(memory_client: Any) -> None:
    """SDK 已创建 Experiment 根时，根也必须得到业务用例 Session。"""
    client, exporter = memory_client
    case = GoldenCase(id="experiment-case", category="test", turns=[{"send_text": "one"}])

    async def transport(request: httpx.Request) -> httpx.Response:
        """使用独立上下文模拟远端 HTTP 服务。"""
        return await asyncio.create_task(_server(request), context=Context())

    with (client.start_as_current_observation(name="experiment-root"),
          langfuse_client.experiment_item_trace()):
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r", client=http)
    client.flush()
    spans = exporter.get_finished_spans()
    assert all(span.attributes.get("session.id") == result.conversation_id for span in spans)


async def test_standalone_case_does_not_inherit_unrelated_ambient_trace(memory_client: Any) -> None:
    """工作台外层已有观测时，独立用例仍有自己的 Trace，不能把多用例串成一棵树。"""
    client, exporter = memory_client
    case = GoldenCase(id="independent", category="test", turns=[{"send_text": "one"}])

    async def transport(request: httpx.Request) -> httpx.Response:
        """HTTP 是服务端唯一的父关联来源。"""
        return await asyncio.create_task(_server(request), context=Context())

    with client.start_as_current_observation(name="unrelated-workbench-request") as outer:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r", client=http)
    client.flush()
    assert result.langfuse_trace_id != outer.trace_id
    rows = [s for s in exporter.get_finished_spans() if f"{s.context.trace_id:032x}" == result.langfuse_trace_id]
    assert len([s for s in rows if s.parent is None]) == 1
    assert all(s.attributes.get("session.id") == result.conversation_id for s in rows)
