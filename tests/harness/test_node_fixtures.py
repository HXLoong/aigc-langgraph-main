from __future__ import annotations

import json

import pytest

from harness.node_annotations import NodeDefinition, NodeObservation


def test_store_writes_projected_field_annotation(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureStore

    definition = NodeDefinition(
        name="swap_intent",
        product_type="swap",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input_fields=("raw_text", "quote_content"),
        output_fields=("intent",),
    )
    observation = NodeObservation(
        observation_id="obs-1234567890",
        trace_id="trace-1",
        turn=2,
        name="swap_intent",
        product_type="swap",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input={
            "raw_text": "确认下单",
            "quote_content": "订单卡片",
            "user_id": "sensitive-user",
        },
        output={"intent": "confirm_order", "trace": []},
    )
    store = NodeFixtureStore(tmp_path, registry={"swap_intent": definition})

    path = store.save(
        observation,
        case_id="case-001",
        annotator="LLW",
        mode="fields",
        expected_fields={"/intent": "confirm_order"},
    )

    assert path == tmp_path / "swap" / "swap_intent.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["input"] == {
        "raw_text": "确认下单",
        "quote_content": "订单卡片",
    }
    assert records[0]["expected"] == {
        "mode": "fields",
        "fields": {"/intent": "confirm_order"},
    }
    assert records[0]["source"]["observation_id"] == "obs-1234567890"
    assert records[0]["annotation"]["annotator"] == "LLW"


def test_store_updates_existing_observation_instead_of_duplicating(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureStore

    definition = NodeDefinition(
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input_fields=("raw_text",),
        output_fields=("intent",),
    )
    observation = NodeObservation(
        observation_id="obs-same",
        trace_id="trace-1",
        turn=1,
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input={"raw_text": "确认"},
        output={"intent": "confirm_order"},
    )
    store = NodeFixtureStore(tmp_path, registry={"option_intent": definition})
    store.save(
        observation,
        case_id="case-001",
        annotator="HXL",
        mode="fields",
        expected_fields={"/intent": "unknown_intent"},
    )
    path = store.save(
        observation,
        case_id="case-001",
        annotator="HXL",
        mode="fields",
        expected_fields={"/intent": "confirm_order"},
    )

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["expected"]["fields"]["/intent"] == "confirm_order"


def test_store_projects_object_annotation_to_declared_output_fields(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureStore

    definition = NodeDefinition(
        name="swap_intent",
        product_type="swap",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input_fields=("raw_text",),
        output_fields=("intent",),
    )
    observation = NodeObservation(
        observation_id="obs-object",
        trace_id="trace-object",
        turn=1,
        name="swap_intent",
        product_type="swap",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input={"raw_text": "确认"},
        output={"intent": "confirm_order", "trace": [{"node": "swap_intent"}]},
    )
    store = NodeFixtureStore(tmp_path, registry={"swap_intent": definition})

    path = store.save(
        observation,
        case_id="case-object",
        annotator="LLW",
        mode="object",
        expected_object=observation.output,
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["expected"] == {
        "mode": "object",
        "value": {"intent": "confirm_order"},
    }


def test_store_rejects_field_outside_declared_outputs(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureError, NodeFixtureStore

    definition = NodeDefinition(
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input_fields=("raw_text",),
        output_fields=("intent",),
    )
    observation = NodeObservation(
        observation_id="obs-invalid-field",
        trace_id="trace-invalid-field",
        turn=1,
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input={"raw_text": "确认"},
        output={"intent": "confirm_order", "trace": []},
    )
    store = NodeFixtureStore(tmp_path, registry={"option_intent": definition})

    with pytest.raises(NodeFixtureError, match="不允许标注的输出字段"):
        store.save(
            observation,
            case_id="case-invalid",
            annotator="HXL",
            mode="fields",
            expected_fields={"/trace": []},
        )


def test_store_allows_selected_nested_field_from_actual_output(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureStore

    definition = NodeDefinition(
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        output_fields=("intent",),
    )
    observation = NodeObservation(
        observation_id="obs-nested-output",
        trace_id="trace-nested-output",
        turn=1,
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        output={
            "intent": "new_inquiry",
            "field_records": {"option/intent": {"value": "new_inquiry"}},
        },
    )
    store = NodeFixtureStore(tmp_path, registry={"option_intent": definition})

    path = store.save(
        observation,
        case_id="case-nested",
        annotator="LLW",
        mode="fields",
        expected_fields={"/field_records/option~1intent/value": "new_inquiry"},
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["expected"]["fields"] == {
        "/field_records/option~1intent/value": "new_inquiry"
    }


def test_store_rejects_field_not_present_in_actual_output(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureError, NodeFixtureStore

    definition = NodeDefinition(
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        output_fields=("intent",),
    )
    observation = NodeObservation(
        observation_id="obs-missing-output",
        trace_id="trace-missing-output",
        turn=1,
        name="option_intent",
        product_type="option",
        category="意图识别",
        replayable=True,
        side_effect="none",
        output={"intent": "new_inquiry", "field_records": {"option": {}}},
    )
    store = NodeFixtureStore(tmp_path, registry={"option_intent": definition})

    with pytest.raises(NodeFixtureError, match="不允许标注的输出字段"):
        store.save(
            observation,
            case_id="case-missing",
            annotator="LLW",
            mode="fields",
            expected_fields={"/intent/missing": "new_inquiry"},
        )


def test_store_allows_write_node_annotation_but_marks_it_non_replayable(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureStore
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    definition = DEFAULT_NODE_REGISTRY["swap_confirm"]
    observation = NodeObservation(
        observation_id="obs-write",
        trace_id="trace-write",
        turn=2,
        name="swap_confirm",
        product_type="swap",
        category="后端写入",
        replayable=False,
        side_effect="write",
        output_fields=definition.output_fields,
        input={"raw_text": "确认下单"},
        output={
            "expected_action": "place",
            "confirm": {"action": "place", "orderList": [{"orderId": "H-1"}]},
            "api_code": 0,
            "api_result": "成功",
            "reply_text": "成功",
        },
    )
    store = NodeFixtureStore(tmp_path, registry={"swap_confirm": definition})

    path = store.save(
        observation,
        case_id="case-write",
        annotator="LLW",
        mode="fields",
        expected_fields={"/api_code": 0, "/expected_action": "place"},
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["expected"]["fields"] == {
        "/api_code": 0,
        "/expected_action": "place",
    }
    assert record["replay"] == {"enabled": False, "side_effect": "write"}


def test_store_rejects_view_only_node_annotation(tmp_path) -> None:
    from harness.node_annotations import NodeDefinition
    from harness.node_fixtures import NodeFixtureError, NodeFixtureStore

    definition = NodeDefinition(
        name="fallback",
        product_type="common",
        category="输出处理",
        replayable=False,
        side_effect="none",
        annotatable=False,
        annotation_reason="仅输出动态 trace，无稳定业务输出",
    )
    observation = NodeObservation(
        observation_id="obs-view-only",
        trace_id="trace-view-only",
        turn=1,
        name="fallback",
        product_type="common",
        category="输出处理",
        replayable=False,
        side_effect="none",
        annotatable=False,
        annotation_reason=definition.annotation_reason,
        output={"trace": [{"node": "fallback", "elapsed_ms": 1}]},
    )
    store = NodeFixtureStore(tmp_path, registry={"fallback": definition})

    with pytest.raises(NodeFixtureError, match="仅支持查看"):
        store.save(
            observation,
            case_id="case-view-only",
            annotator="LLW",
            mode="object",
            expected_object={},
        )


def test_store_saves_auto_discovered_node_without_registry_entry(tmp_path) -> None:
    from harness.node_fixtures import NodeFixtureStore

    observation = NodeObservation(
        observation_id="obs-future",
        trace_id="trace-future",
        turn=1,
        name="finish_instructions",
        product_type="common",
        category="自动发现",
        replayable=False,
        side_effect="unknown",
        output_fields=("instruction_results", "reply_text"),
        input={"_results": {}},
        output={"instruction_results": [], "reply_text": "执行完成", "trace": []},
    )
    store = NodeFixtureStore(tmp_path, registry={})

    path = store.save(
        observation,
        case_id="case-future",
        annotator="LLW",
        mode="fields",
        expected_fields={"/reply_text": "执行完成"},
    )

    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record["node_name"] == "finish_instructions"
    assert record["replay"] == {"enabled": False, "side_effect": "unknown"}


@pytest.mark.parametrize(
    "sensitive_input",
    [
        {"raw_text": "QWEN_API_KEY=sk-dummy-secret-value"},
        {"raw_text": "Authorization: Bearer dummy-access-token"},
        {"raw_text": "正常输入", "cookie": "session=dummy-cookie"},
    ],
)
def test_store_rejects_sensitive_data_before_writing(tmp_path, sensitive_input) -> None:
    from harness.node_fixtures import NodeFixtureError, NodeFixtureStore

    definition = NodeDefinition(
        name="swap_intent",
        product_type="swap",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input_fields=tuple(sensitive_input),
        output_fields=("intent",),
    )
    observation = NodeObservation(
        observation_id="obs-sensitive",
        trace_id="trace-sensitive",
        turn=1,
        name="swap_intent",
        product_type="swap",
        category="意图识别",
        replayable=True,
        side_effect="none",
        input=sensitive_input,
        output={"intent": "unknown_intent"},
    )
    store = NodeFixtureStore(tmp_path, registry={"swap_intent": definition})

    with pytest.raises(NodeFixtureError, match="敏感信息"):
        store.save(
            observation,
            case_id="case-sensitive",
            annotator="security-audit",
            mode="fields",
            expected_fields={"/intent": "unknown_intent"},
        )

    assert not list(tmp_path.rglob("*.jsonl"))
