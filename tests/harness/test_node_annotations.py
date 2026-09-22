from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest


def test_extract_trace_references_prefers_per_turn_langfuse_traces() -> None:
    from harness.node_annotations import extract_trace_references

    case_result = {
        "trace_id": "parent-trace",
        "turns": [
            {"outputs": {"langfuse_trace_id": "turn-1"}},
            {"outputs": {"langfuse_trace_id": "turn-2"}},
            {"outputs": {"langfuse_trace_id": "turn-2"}},
        ],
    }

    assert extract_trace_references(case_result) == [
        {"turn": 1, "trace_id": "turn-1"},
        {"turn": 2, "trace_id": "turn-2"},
    ]


def test_extract_trace_references_ignores_business_request_trace_ids() -> None:
    from harness.node_annotations import extract_trace_references

    case_result = {
        "turns": [
            {"outputs": {"trace_id": "request-trace-1"}},
            {"outputs": {"trace_id": "request-trace-2"}},
        ]
    }

    assert extract_trace_references(case_result) == []


def test_load_case_nodes_rejects_report_without_langfuse_trace_before_client(
    monkeypatch,
) -> None:
    from harness import node_annotations

    class UnexpectedClient:
        def __init__(self, **_: object) -> None:
            raise AssertionError("缺少 Langfuse Trace 时不应创建客户端")

    settings = SimpleNamespace(
        enable_langfuse=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_base_url="https://langfuse.test",
    )
    monkeypatch.setattr(node_annotations, "get_settings", lambda: settings)

    with pytest.raises(ValueError, match="没有可用的 Langfuse Trace"):
        node_annotations.load_case_nodes_from_langfuse(
            {"turns": [{"outputs": {"trace_id": "business-trace"}}]},
            client_factory=UnexpectedClient,
            registry={},
        )


def test_normalize_node_observations_keeps_graph_nodes_and_ignores_nested_llm() -> None:
    from harness.node_annotations import (
        NodeDefinition,
        normalize_node_observations,
    )

    registry = {
        "swap_intent": NodeDefinition(
            name="swap_intent",
            product_type="swap",
            category="意图识别",
            replayable=True,
            side_effect="none",
            input_fields=("raw_text", "quote_content"),
            output_fields=("intent",),
        )
    }
    observations = [
        {
            "id": "obs-node",
            "name": "swap_intent",
            "type": "CHAIN",
            "start_time": "2026-09-20T06:00:00Z",
            "input": json.dumps({"raw_text": "确认下单", "trace_id": "internal"}),
            "output": json.dumps({"intent": "confirm_order", "trace": []}),
            "metadata": {"langgraph_node": "swap_intent"},
        },
        {
            "id": "obs-llm",
            "name": "_ChatLLM",
            "type": "GENERATION",
            "input": "{}",
            "output": "{}",
            "metadata": {"langgraph_node": "swap_intent"},
        },
    ]

    nodes = normalize_node_observations(
        observations,
        trace_id="trace-1",
        turn=2,
        registry=registry,
    )

    assert [node.observation_id for node in nodes] == ["obs-node"]
    assert nodes[0].name == "swap_intent"
    assert nodes[0].turn == 2
    assert nodes[0].input["raw_text"] == "确认下单"
    assert nodes[0].output["intent"] == "confirm_order"
    assert nodes[0].output_fields == ("intent",)
    assert nodes[0].replayable is True
    assert nodes[0].annotatable is True
    assert nodes[0].annotation_reason == ""


def test_normalize_node_observations_accepts_display_labels_but_ignores_route_spans() -> None:
    from harness.node_annotations import (
        NodeDefinition,
        normalize_node_observations,
    )

    registry = {
        "ingest": NodeDefinition(
            name="ingest",
            product_type="common",
            category="输入处理",
            replayable=True,
            side_effect="none",
            output_fields=("reply_text",),
        )
    }
    observations = [
        {
            "id": "obs-route",
            "name": "消息接收与状态初始化 · 路由判断 [ingest/_route_entry]",
            "input": {},
            "output": {},
            "metadata": {"langgraph_node": "ingest"},
        },
        {
            "id": "obs-node",
            "name": "消息接收与状态初始化 [ingest]",
            "input": {"raw_text": "询价"},
            "output": {"reply_text": "处理中"},
            "metadata": {"langgraph_node": "ingest"},
        },
    ]

    nodes = normalize_node_observations(
        observations,
        trace_id="trace-labeled",
        turn=1,
        registry=registry,
    )

    assert [node.observation_id for node in nodes] == ["obs-node"]
    assert nodes[0].name == "ingest"


def test_unregistered_future_node_is_auto_discovered_without_replay() -> None:
    from harness.node_annotations import normalize_node_observations

    observations = [
        {
            "id": "obs-future",
            "name": "future_summary",
            "start_time": "2026-09-21T06:00:00Z",
            "input": {"_results": {}},
            "output": {
                "summary_results": [{"status": "response_received"}],
                "reply_text": "执行完成",
                "trace": [{"node": "future_summary"}],
            },
            "metadata": {"langgraph_node": "future_summary"},
        }
    ]

    nodes = normalize_node_observations(
        observations,
        trace_id="trace-future",
        turn=1,
        registry={},
    )

    assert [node.name for node in nodes] == ["future_summary"]
    assert nodes[0].product_type == "common"
    assert nodes[0].category == "自动发现"
    assert nodes[0].output_fields == ("summary_results", "reply_text")
    assert nodes[0].annotatable is True
    assert nodes[0].replayable is False
    assert nodes[0].side_effect == "unknown"


def test_unregistered_trace_only_node_is_auto_discovered_as_view_only() -> None:
    from harness.node_annotations import normalize_node_observations

    nodes = normalize_node_observations(
        [
            {
                "id": "obs-future-trace",
                "name": "future_internal_node",
                "output": {"trace": [{"node": "future_internal_node"}]},
                "metadata": {"langgraph_node": "future_internal_node"},
            }
        ],
        trace_id="trace-future",
        turn=1,
        registry={},
    )

    assert len(nodes) == 1
    assert nodes[0].annotatable is False
    assert nodes[0].annotation_reason
    assert nodes[0].output_fields == ()


def test_read_trace_observations_follows_langfuse_cursor_pages() -> None:
    from harness.node_annotations import read_trace_observations

    class ObservationResource:
        def get_many(self, *, cursor: str | None = None, **_: object) -> object:
            if cursor is None:
                return SimpleNamespace(
                    data=[{"id": "obs-1"}],
                    meta=SimpleNamespace(cursor="next-page"),
                )
            return SimpleNamespace(
                data=[{"id": "obs-2"}],
                meta=SimpleNamespace(cursor=None),
            )

    api = SimpleNamespace(observations=ObservationResource())

    assert read_trace_observations(api, "trace-1") == [
        {"id": "obs-1"},
        {"id": "obs-2"},
    ]


def test_read_trace_observations_retries_transient_connect_timeout_per_page() -> None:
    from harness.node_annotations import read_trace_observations

    calls: list[str | None] = []

    class ObservationResource:
        def get_many(self, *, cursor: str | None = None, **_: object) -> object:
            calls.append(cursor)
            if cursor is None:
                return SimpleNamespace(
                    data=[{"id": "obs-1"}],
                    meta=SimpleNamespace(cursor="next-page"),
                )
            if calls.count("next-page") == 1:
                raise httpx.ConnectTimeout("transient connection timeout")
            return SimpleNamespace(
                data=[{"id": "obs-2"}],
                meta=SimpleNamespace(cursor=None),
            )

    api = SimpleNamespace(observations=ObservationResource())

    assert read_trace_observations(api, "trace-1") == [
        {"id": "obs-1"},
        {"id": "obs-2"},
    ]
    assert calls == [None, "next-page", "next-page"]


def test_read_trace_observations_recovers_after_two_connect_timeouts() -> None:
    from harness.node_annotations import read_trace_observations

    attempts = 0

    class ObservationResource:
        def get_many(self, **_: object) -> object:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise httpx.ConnectTimeout("transient connection timeout")
            return SimpleNamespace(data=[{"id": "obs-1"}], meta=None)

    api = SimpleNamespace(observations=ObservationResource())

    assert read_trace_observations(api, "trace-1") == [{"id": "obs-1"}]
    assert attempts == 3


def test_read_trace_observations_reports_repeated_connect_timeout() -> None:
    from harness.node_annotations import read_trace_observations

    attempts = 0

    class ObservationResource:
        def get_many(self, **_: object) -> object:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectTimeout("connection timed out")

    api = SimpleNamespace(observations=ObservationResource())

    with pytest.raises(httpx.ConnectTimeout):
        read_trace_observations(api, "trace-1")
    assert attempts == 3


def test_default_registry_marks_write_nodes_as_non_replayable() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    assert DEFAULT_NODE_REGISTRY["swap_intent"].replayable is True
    assert DEFAULT_NODE_REGISTRY["swap_intent"].side_effect == "none"
    assert DEFAULT_NODE_REGISTRY["option_intent"].product_type == "option"
    assert DEFAULT_NODE_REGISTRY["swap_place_order_submit"].replayable is False
    assert DEFAULT_NODE_REGISTRY["swap_place_order_submit"].side_effect == "write"
    assert DEFAULT_NODE_REGISTRY["option_extract_place"].replayable is False


def test_write_nodes_declare_stable_outputs_for_annotation() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    required_outputs = {
        "quick_inquiry": {"api_code", "api_result", "reply_text"},
        "swap_place_order_submit": {"place_params", "api_code", "api_result", "reply_text"},
        "swap_confirm": {"expected_action", "confirm", "api_code", "api_result", "reply_text"},
        "swap_cancel": {"expected_action", "cancel_params", "api_code", "api_result", "reply_text"},
        "option_extract_inquiry": {
            "expected_action",
            "place_params",
            "api_code",
            "api_result",
            "reply_text",
        },
        "inquiry_submit": {
            "expected_action",
            "place_params",
            "api_code",
            "api_result",
            "reply_text",
        },
        "option_extract_place": {
            "expected_action",
            "place_params",
            "api_code",
            "api_result",
            "reply_text",
        },
        "option_extract_confirm_place": {
            "expected_action",
            "confirm",
            "api_code",
            "api_result",
            "reply_text",
        },
        "option_extract_cancel_place": {
            "expected_action",
            "cancel_params",
            "api_code",
            "api_result",
            "reply_text",
        },
        "option_extract_cancel": {
            "expected_action",
            "cancel_params",
            "api_code",
            "api_result",
            "reply_text",
        },
        "option_extract_confirm_cancel": {
            "expected_action",
            "confirm",
            "api_code",
            "api_result",
            "reply_text",
        },
    }

    for node_name, expected in required_outputs.items():
        definition = DEFAULT_NODE_REGISTRY[node_name]
        assert definition.side_effect == "write"
        assert definition.replayable is False
        assert expected <= set(definition.output_fields), node_name


def test_remaining_nodes_have_explicit_annotation_contract() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    stable_outputs = {
        "ingest": {
            "reply_text",
            "api_result",
            "api_code",
            "error",
            "expected_action",
            "tickers",
            "place_params",
            "cancel_params",
            "confirm",
            "query_filter",
            "close_params",
            "ticker_hitl_candidates",
            "swap_counterparty_picks",
            "swap_ticker_picks",
        },
        "pre_route": {
            "option_counterparties",
            "swap_counterparties",
            "quote_ticker_candidates",
        },
        "intent_route": {"product_type", "swap_input_mode"},
        "render": {"reply_text"},
        "remember_confirmed_params": {"last_confirmed_params"},
        "record_history": {"history_messages"},
    }
    replayable = {
        "ingest",
        "pre_route",
        "intent_route",
        "render",
        "remember_confirmed_params",
        "record_history",
    }
    for node_name, expected in stable_outputs.items():
        definition = DEFAULT_NODE_REGISTRY[node_name]
        assert definition.annotatable is True
        assert expected <= set(definition.output_fields), node_name
        assert definition.replayable is (node_name in replayable)
        assert definition.callable_path

    trace_only = {
        "fallback",
        "persist_intent",
        "persist",
        "swap_unknown",
        "option_unknown",
        "close_unknown",
    }
    for node_name in trace_only:
        definition = DEFAULT_NODE_REGISTRY[node_name]
        assert definition.annotatable is False
        assert definition.annotation_reason
        assert definition.output_fields == ()


def test_node_discovery_does_not_require_registry_count_to_match_graph_count() -> None:
    from harness.node_annotations import normalize_node_observations
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    future_names = {
        "initialize_instructions",
        "schedule_instructions",
        "prepare_instruction",
        "submit_instruction_batches",
        "future_summary",
    }
    observations = [
        {
            "id": f"obs-{index}",
            "name": name,
            "output": {"result": name},
            "metadata": {"langgraph_node": name},
        }
        for index, name in enumerate(sorted(future_names), start=1)
    ]

    nodes = normalize_node_observations(
        observations,
        trace_id="trace-growing-graph",
        turn=1,
        registry=DEFAULT_NODE_REGISTRY,
    )

    assert {node.name for node in nodes} == future_names
    assert all(node.replayable is False for node in nodes)


def test_default_registry_covers_close_and_backend_owned_instrument_nodes() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    required = {
        "close_intent",
        "close_holding_query",
        "close_place_close",
        "close_confirm_close",
        "close_cancel_close",
        "close_confirm_cancel",
        "close_query_status",
        "close_unknown",
        "place_close_parse",
        "place_close_fetch_orders",
        "place_close_extract",
        "place_close_normalize",
        "place_close_validate",
        "place_close_submit",
        "place_close_reject",
        "swap_extract_candidates",
        "swap_normalize",
        "swap_place_result",
        "inquiry_extract",
        "inquiry_normalize",
        "inquiry_submit",
    }

    assert required <= DEFAULT_NODE_REGISTRY.keys()
    assert DEFAULT_NODE_REGISTRY["close_intent"].product_type == "option_close"
    assert DEFAULT_NODE_REGISTRY["swap_extract_candidates"].product_type == "swap"
    assert not any(node.product_type == "ticker" for node in DEFAULT_NODE_REGISTRY.values())


def test_read_only_backend_nodes_are_replayable_but_write_nodes_are_not() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    for name in (
        "swap_query_order",
        "option_extract_query",
        "close_holding_query",
        "close_query_status",
    ):
        definition = DEFAULT_NODE_REGISTRY[name]
        assert definition.side_effect == "read"
        assert definition.replayable is True
        assert definition.callable_path
        assert definition.output_fields

    for name in (
        "swap_place_order_submit",
        "option_extract_inquiry",
        "place_close_submit",
        "close_confirm_close",
        "close_cancel_close",
        "close_confirm_cancel",
    ):
        definition = DEFAULT_NODE_REGISTRY[name]
        assert definition.side_effect == "write"
        assert definition.replayable is False


def test_collect_case_nodes_aggregates_each_turn_trace() -> None:
    from harness.node_annotations import NodeDefinition, collect_case_nodes

    class ObservationResource:
        def get_many(self, *, trace_id: str, **_: object) -> object:
            return SimpleNamespace(
                data=[
                    {
                        "id": f"obs-{trace_id}",
                        "name": "option_intent",
                        "input": '{"raw_text":"确认"}',
                        "output": '{"intent":"confirm_order"}',
                        "metadata": {"langgraph_node": "option_intent"},
                    }
                ],
                meta=SimpleNamespace(cursor=None),
            )

    registry = {
        "option_intent": NodeDefinition(
            name="option_intent",
            product_type="option",
            category="意图识别",
            replayable=True,
            side_effect="none",
        )
    }
    case_result = {
        "turns": [
            {"outputs": {"langfuse_trace_id": "trace-a"}},
            {"outputs": {"langfuse_trace_id": "trace-b"}},
        ]
    }

    nodes = collect_case_nodes(
        case_result,
        SimpleNamespace(observations=ObservationResource()),
        registry=registry,
    )

    assert [(node.turn, node.trace_id) for node in nodes] == [
        (1, "trace-a"),
        (2, "trace-b"),
    ]


def test_load_case_nodes_from_langfuse_uses_project_settings(monkeypatch) -> None:
    from harness import node_annotations

    captured: dict[str, object] = {}

    class ObservationResource:
        def get_many(self, **_: object) -> object:
            return SimpleNamespace(data=[], meta=SimpleNamespace(cursor=None))

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.api = SimpleNamespace(observations=ObservationResource())
            self.closed = False

        def shutdown(self) -> None:
            self.closed = True

    settings = SimpleNamespace(
        enable_langfuse=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_base_url="https://langfuse.test",
    )
    monkeypatch.setattr(node_annotations, "get_settings", lambda: settings)

    nodes = node_annotations.load_case_nodes_from_langfuse(
        {"trace_id": "trace-1", "turns": []},
        client_factory=FakeClient,
        registry={},
    )

    assert nodes == []
    assert captured == {
        "public_key": "pk-test",
        "secret_key": "sk-test",
        "base_url": "https://langfuse.test",
        "timeout": 15,
    }


def test_load_case_nodes_from_langfuse_does_not_shutdown_shared_client(monkeypatch) -> None:
    from harness import node_annotations

    shutdown_calls = 0

    class ObservationResource:
        def get_many(self, **_: object) -> object:
            return SimpleNamespace(data=[], meta=SimpleNamespace(cursor=None))

    class FakeClient:
        def __init__(self, **_: object) -> None:
            self.api = SimpleNamespace(observations=ObservationResource())

        def shutdown(self) -> None:
            nonlocal shutdown_calls
            shutdown_calls += 1

    settings = SimpleNamespace(
        enable_langfuse=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_base_url="https://langfuse.test",
    )
    monkeypatch.setattr(node_annotations, "get_settings", lambda: settings)
    case_result = {"trace_id": "trace-1", "turns": []}

    node_annotations.load_case_nodes_from_langfuse(
        case_result,
        client_factory=FakeClient,
        registry={},
    )
    node_annotations.load_case_nodes_from_langfuse(
        case_result,
        client_factory=FakeClient,
        registry={},
    )

    assert shutdown_calls == 0
