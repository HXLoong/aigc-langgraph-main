"""Display names must not change the graph, observation tree or model accounting."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from types import SimpleNamespace
from typing import TypedDict
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import PydanticToolsParser
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field


def _labels():
    assert importlib.util.find_spec("app.observability.node_labels"), "missing node label catalogue"
    return importlib.import_module("app.observability.node_labels")


def _factory(**kwargs):
    from app.observability import tracing

    factory = getattr(tracing, "create_callback_handler", None)
    assert callable(factory), "missing shared localized callback factory"
    return factory(**kwargs)


def test_tracing_entrypoint_imports_without_preloading_business_graph():
    result = subprocess.run(
        [sys.executable, "-c", "import app.observability.tracing"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_catalogue_covers_registered_graphs_and_model_kinds():
    from app.graph.main import build_main_graph
    from app.subgraphs.close.graph import build_close_graph
    from app.subgraphs.close.place_close import build_place_close_graph
    from app.subgraphs.option.extract_inquiry import build_inquiry_graph
    from app.subgraphs.option.graph import build_option_graph
    from app.subgraphs.swap.graph import build_swap_graph
    from app.subgraphs.swap.place_order import build_place_graph

    labels = _labels().NODE_LABELS
    graphs = [build_main_graph(), build_swap_graph(),
              build_place_graph(), build_option_graph(), build_inquiry_graph(), build_close_graph(),
              build_place_close_graph()]
    for graph in graphs:
        assert set(graph.builder.nodes) - {n for n in graph.builder.nodes
                                          if n.startswith("__error_handler__")} <= labels.keys()
        for node, branches in graph.builder.branches.items():
            for name, branch in branches.items():
                original = branch.path.name or name
                display = _labels().label_observation(
                    original, kind="chain", metadata={"langgraph_node": node}, parent_node=node,
                )
                assert any("\u4e00" <= char <= "\u9fff" for char in display.name), (node, original)
                assert display.node_id == node
    assert labels["entry_route"].kind == "code"
    assert labels["inquiry_extract"].kind == "llm"
    assert labels["option_intent"].kind == "hybrid"
    assert labels["inquiry_normalize"].kind == "code"
    assert labels["quick_inquiry"].kind == "io"
    assert labels["option_close"].kind == "graph"


@pytest.mark.parametrize("name,kind,node,parent,expected", [
    ("LangGraph", "chain", None, None, "交易指令处理 [main_graph]"),
    ("entry_route", "chain", "entry_route", "main_graph", "业务入口分流 [entry_route]"),
    ("select_entry_branch", "chain", "entry_route", None,
     "业务入口分流 · 路由判断 [entry_route/select_entry_branch]"),
    ("select_entry_branch", "chain", None, "entry_route",
     "业务入口分流 · 路由判断 [entry_route/select_entry_branch]"),
    ("select_custom_branch", "chain", "entry_route", None, "select_custom_branch"),
    ("LangGraph", "chain", "option_close", "option_close", "期权平仓子图 [option_close/graph]"),
    ("option_intent", "chain", "option_intent", "option", "[Code/LLM] 期权意图识别 [option_intent]"),
    ("inquiry_extract", "chain", "inquiry_extract", "option", "[LLM] 期权询价要素抽取 [inquiry_extract]"),
    ("_ChatLLM", "llm", "inquiry_extract", None, "[LLM] 期权询价要素抽取 · 模型调用 [inquiry_extract/llm]"),
    ("RunnableSequence", "chain", "inquiry_extract", None, "期权询价要素抽取 · 结构化处理链 [inquiry_extract/chain]"),
    ("PydanticToolsParser", "chain", "inquiry_extract", None, "期权询价要素抽取 · 输出校验 [inquiry_extract/parser]"),
    ("_router", "chain", "inquiry_extract", None, "期权询价要素抽取 · 路由判断 [inquiry_extract/_router]"),
    ("__error_handler__inquiry_extract", "chain", None, None,
     "期权询价要素抽取 · 重试耗尽处理 [inquiry_extract/error_handler]"),
    ("custom_third_party", "chain", "inquiry_extract", None, "custom_third_party"),
    ("期权开仓专项-case-025", "chain", None, None, "期权开仓专项-case-025"),
])
def test_resolve_names_without_mutating_metadata(name, kind, node, parent, expected):
    metadata = {"langgraph_node": node, "langfuse_session_id": "test-session"} if node else {}
    before = dict(metadata)
    result = _labels().label_observation(name, kind=kind, metadata=metadata, parent_node=parent)
    assert result.name == expected
    assert metadata == before
    assert result.metadata["otc_original_run_name"] == name
    assert result.metadata.get("langfuse_session_id") == metadata.get("langfuse_session_id")


@pytest.fixture
def memory_langfuse():
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter, provider = InMemorySpanExporter(), TracerProvider()
    public_key = f"pk-lf-local-label-test-{uuid4().hex}"
    client = Langfuse(public_key=public_key, secret_key="synthetic-test-key",
                      base_url="http://langfuse.invalid", tracer_provider=provider,
                      span_exporter=exporter, tracing_enabled=True)
    try:
        yield client, exporter, public_key
    finally:
        client.shutdown()


@pytest.mark.parametrize("flags,expected", [
    ({"fast_query": "1"}, "quick_inquiry"),
    ({"existing_command": "1", "at_bot": False}, "existing_command_query"),
    ({}, "pre_route"),
])
async def test_entry_route_labels_preserve_identity_and_span_parent(memory_langfuse, flags, expected):
    from app.graph.state import AgentState
    from app.nodes.entry_route import entry_route, select_entry_branch

    client, exporter, public_key = memory_langfuse
    graph = StateGraph(AgentState)
    graph.add_node("entry_route", entry_route)
    graph.add_edge(START, "entry_route")
    graph.add_conditional_edges("entry_route", select_entry_branch, {
        branch: END for branch in ("quick_inquiry", "existing_command_query", "pre_route")
    })
    handler = _factory(public_key=public_key)
    result = await graph.compile().ainvoke(flags, config={"callbacks": [handler]})
    assert result["trace"][0].node == "entry_route"
    assert result["trace"][0].decision == expected
    client.flush()
    prefix = "langfuse.observation.metadata."
    spans = exporter.get_finished_spans()
    entry = next(s for s in spans if s.attributes.get(prefix + "otc_original_run_name") == "entry_route")
    branch = next(s for s in spans if s.attributes.get(prefix + "otc_original_run_name") == "select_entry_branch")
    assert entry.name == "业务入口分流 [entry_route]"
    assert branch.name == "业务入口分流 · 路由判断 [entry_route/select_entry_branch]"
    assert branch.parent.span_id == entry.context.span_id
    for span in (entry, branch):
        assert span.attributes[prefix + "otc_node_id"] == "entry_route"
        assert span.attributes[prefix + "otc_node_label_zh"] == "业务入口分流"
    assert all(s.attributes.get("langfuse.observation.type") != "generation" for s in spans)
    assert not handler._name_contexts


class _State(TypedDict, total=False):
    first: bool
    second: bool


class _Verdict(BaseModel):
    passed: bool = Field(description="合成测试结果")


def _synthetic_graph():
    model = FakeMessagesListChatModel(responses=[AIMessage(
        content="", tool_calls=[{"name": "_Verdict", "args": {"passed": True}, "id": "fake-call"}],
        response_metadata={"model_name": "synthetic-label-model"},
        usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
    )])
    chain = model | PydanticToolsParser(tools=[_Verdict], first_tool_only=True)

    async def first(state):
        verdict = await chain.ainvoke([HumanMessage(content="synthetic naming test")])
        return {"first": verdict.passed}

    async def second(state):
        await asyncio.sleep(0)
        return {"second": True}

    graph = StateGraph(_State)
    graph.add_node("inquiry_extract", first)
    graph.add_node("inquiry_normalize", second)
    graph.add_edge(START, "inquiry_extract")
    graph.add_edge(START, "inquiry_normalize")
    graph.add_edge("inquiry_extract", END)
    graph.add_edge("inquiry_normalize", END)
    return graph.compile()


async def test_real_sdk_preserves_tree_model_usage_and_node_identity(memory_langfuse):
    from langfuse.langchain import CallbackHandler

    client, exporter, public_key = memory_langfuse
    graph = _synthetic_graph()
    baseline = CallbackHandler(public_key=public_key, trace_context={"trace_id": "a" * 32})
    baseline.run_inline = True
    localized = _factory(public_key=public_key, trace_context={"trace_id": "b" * 32})
    for handler in (baseline, localized):
        result = await graph.ainvoke({}, config={"callbacks": [handler], "metadata": {
            "langfuse_session_id": "synthetic-naming-session",
            "ls_model_name": "synthetic-label-model",
        }})
        assert result == {"first": True, "second": True}
    client.flush()
    spans = exporter.get_finished_spans()
    groups = [[s for s in spans if f"{s.context.trace_id:032x}" == tid * 32] for tid in ("a", "b")]
    assert groups[0] and len(groups[0]) == len(groups[1])

    def metadata(span):
        prefix = "langfuse.observation.metadata."
        return {k.removeprefix(prefix): v for k, v in span.attributes.items() if k.startswith(prefix)}

    def original(span):
        return metadata(span).get("otc_original_run_name", span.name)

    def shape(rows):
        by_id = {s.context.span_id: s for s in rows}
        return Counter((original(s), original(by_id[s.parent.span_id])
                        if s.parent and s.parent.span_id in by_id else None) for s in rows)

    assert shape(groups[0]) == shape(groups[1])
    translated = groups[1]
    assert any(s.name == "[LLM] 期权询价要素抽取 [inquiry_extract]" for s in translated)
    generation = next(s for s in translated if s.attributes.get("langfuse.observation.type") == "generation")
    assert generation.name.endswith("[inquiry_extract/llm]") and generation.name.startswith("[LLM]")
    assert "synthetic-label-model" in generation.attributes.values()
    assert json.loads(generation.attributes["langfuse.observation.usage_details"]) == {
        "input": 3, "output": 1, "total": 4,
    }
    assert metadata(generation)["langgraph_node"] == "inquiry_extract"
    assert all(s.attributes.get("session.id") == "synthetic-naming-session" for s in translated)
    assert any(s.name == "期权询价参数归一化 [inquiry_normalize]" for s in translated)
    assert not localized._name_contexts


def test_parent_context_inheritance_error_cancel_and_unknown_calls(memory_langfuse):
    _, _, public_key = memory_langfuse
    handler = _factory(public_key=public_key)
    a, b, child_a, child_b = (uuid4() for _ in range(4))
    handler.on_chain_start(None, {}, run_id=a, name="inquiry_extract")
    handler.on_chain_start(None, {}, run_id=b, name="swap_normalize")
    handler.on_chain_start(None, {}, run_id=child_a, parent_run_id=a, name="PydanticToolsParser")
    handler.on_chain_start(None, {}, run_id=child_b, parent_run_id=b, name="RunnableSequence")
    assert handler._runs[child_a]._otel_span.name.endswith("[inquiry_extract/parser]")
    assert handler._runs[child_b]._otel_span.name.endswith("[swap_normalize/chain]")
    handler.on_chain_error(ValueError("synthetic"), run_id=child_a)
    handler.on_chain_error(asyncio.CancelledError(), run_id=a)
    assert a not in handler._name_contexts and child_a not in handler._name_contexts
    assert b in handler._name_contexts and child_b in handler._name_contexts
    handler.on_chain_end({}, run_id=child_b)
    handler.on_chain_end({}, run_id=b)
    assert not handler._name_contexts


async def test_nested_parallel_graphs_keep_their_own_labels(memory_langfuse):
    client, exporter, public_key = memory_langfuse
    handler = _factory(public_key=public_key)

    def child(node, output_key):
        async def extract(state):
            model = FakeMessagesListChatModel(responses=[AIMessage(content="synthetic")])
            await model.ainvoke("synthetic", config={"metadata": {"ls_model_name": "synthetic"}})
            return {output_key: True}
        graph = StateGraph(_State)
        graph.add_node(node, extract)
        graph.add_edge(START, node)
        graph.add_edge(node, END)
        return graph.compile()

    graph = StateGraph(_State)
    graph.add_node("option", child("inquiry_extract", "first"))
    graph.add_node("option_close", child("place_close_extract", "second"))
    for name in ("option", "option_close"):
        graph.add_edge(START, name)
        graph.add_edge(name, END)
    assert await graph.compile().ainvoke({}, config={"callbacks": [handler]}) == {"first": True, "second": True}
    client.flush()
    names = [s.name for s in exporter.get_finished_spans()]
    assert "期权平仓子图 [option_close/graph]" in names
    assert "期权开仓与订单操作子图 [option/graph]" in names
    assert "[LLM] 期权询价要素抽取 · 模型调用 [inquiry_extract/llm]" in names
    assert "[LLM] 期权平仓要素抽取 · 模型调用 [place_close_extract/llm]" in names
    assert not handler._name_contexts


async def test_rule_only_hybrid_path_does_not_create_generation(memory_langfuse):
    client, exporter, public_key = memory_langfuse
    graph = StateGraph(_State)
    graph.add_node("option_intent", lambda state: {"first": True})
    graph.add_edge(START, "option_intent")
    graph.add_edge("option_intent", END)
    await graph.compile().ainvoke({}, config={"callbacks": [_factory(public_key=public_key)]})
    client.flush()
    spans = exporter.get_finished_spans()
    assert any(s.name == "[Code/LLM] 期权意图识别 [option_intent]" for s in spans)
    assert not any(s.attributes.get("langfuse.observation.type") == "generation" for s in spans)


def test_handler_keeps_tool_retriever_types_and_error_marking(memory_langfuse, monkeypatch):
    from app.graph.state import ErrorInfo
    from app.observability import tracing

    client, exporter, public_key = memory_langfuse
    handler = _factory(public_key=public_key)
    root, tool, retriever = (uuid4() for _ in range(3))
    handler.on_chain_start(None, {}, run_id=root, name="inquiry_submit")
    handler.on_tool_start({"name": "external_tool"}, "synthetic", run_id=tool, parent_run_id=root)
    handler.on_tool_end("synthetic", run_id=tool)
    handler.on_retriever_start({"name": "external_retriever"}, "synthetic", run_id=retriever, parent_run_id=root)
    handler.on_retriever_error(ValueError("synthetic"), run_id=retriever)
    monkeypatch.setattr(tracing, "_enabled", lambda: True)
    tracing.HandledErrorCallback(handler).on_chain_end(
        {"error": ErrorInfo(node="inquiry_submit", type="ValueError", message="synthetic")}, run_id=root,
    )
    handler.on_chain_end({}, run_id=root)
    client.flush()
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert spans["external_tool"].attributes["langfuse.observation.type"] == "tool"
    assert spans["external_retriever"].attributes["langfuse.observation.type"] == "retriever"
    assert spans["期权询价提交 [inquiry_submit]"].attributes["langfuse.observation.level"] == "ERROR"
    assert not handler._name_contexts


async def test_naming_failure_preserves_original_sdk_trace(memory_langfuse, monkeypatch):
    from app.observability import tracing

    client, exporter, public_key = memory_langfuse
    def unavailable(*args, **kwargs):
        raise ValueError("synthetic naming failure")
    monkeypatch.setattr(tracing, "label_observation", unavailable)
    result = await _synthetic_graph().ainvoke({}, config={"callbacks": [_factory(public_key=public_key)]})
    client.flush()
    assert result == {"first": True, "second": True}
    assert "inquiry_extract" in {s.name for s in exporter.get_finished_spans()}


def test_harness_uses_shared_factory_and_keeps_disable_gate(monkeypatch):
    from app.observability import tracing
    from harness import langfuse_client

    sentinel = object()
    settings = SimpleNamespace(enable_langfuse=True, langfuse_public_key="synthetic-public",
                               langfuse_secret_key="synthetic-secret", langfuse_base_url="http://langfuse.invalid")
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr(tracing, "create_callback_handler", lambda: sentinel)
    monkeypatch.setattr(os, "environ", os.environ.copy())
    langfuse_client.reset_for_test()
    try:
        assert langfuse_client.get_callback_handler() is sentinel
        langfuse_client.reset_for_test()
        settings.enable_langfuse = False
        assert langfuse_client.get_callback_handler() is None
    finally:
        langfuse_client.reset_for_test()


def test_eval_uses_shared_factory_and_keeps_disable_gate(monkeypatch):
    from app.observability import tracing

    # The legacy script bootstraps .env at import; keep that confined to this test.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    from scripts.langfuse import langfuse_eval

    sentinel = object()
    monkeypatch.setattr(tracing, "create_callback_handler", lambda: sentinel)
    monkeypatch.setattr(langfuse_eval, "_langfuse_enabled", lambda: True)
    assert langfuse_eval._graph_callbacks() == [sentinel]
    monkeypatch.setattr(langfuse_eval, "_langfuse_enabled", lambda: False)
    assert langfuse_eval._graph_callbacks() == []
