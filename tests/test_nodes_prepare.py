"""节点 State 准备：裁剪、转换、完整诊断与执行兼容性。"""

from __future__ import annotations

import copy
import json
from typing import Any, TypedDict
from typing import Any, TypedDict
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.extraction.intent_evidence import IntentEvidence
from app.main import app
from app.node_execution.executor import NodeExecutor
from app.node_execution.registry import NodeRegistration, build_registry
from app.subgraphs.close.models import CloseIntentOutput
from app.subgraphs.close.reference_parser import parse_reference_message
from tests.intent_fixtures import intent_reply

CONTEXT = {
    "conversation_id": "prepare-test",
    "room_id": "room-1",
    "user_id": "user-1",
    "message_id": 123,
}


def _stable(output: dict[str, Any]) -> dict[str, Any]:
    """trace 条目的 id / elapsed_ms 每次运行都不同，比较业务输出时剔除。"""
    stable = copy.deepcopy(output)
    stable["trace"] = [
        {key: value for key, value in entry.items() if key not in {"id", "elapsed_ms"}}
        for entry in stable.get("trace") or []
    ]
    return stable


@pytest.fixture(autouse=True)
def node_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "node_executor", NodeExecutor(build_registry()), raising=False)


async def post_prepare(product: str, node: str, state: Any) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            "/v1/nodes/prepare",
            json={"product": product, "node": node, "langfuse_input": state},
        )


async def test_close_intent_example_keeps_only_declared_fields() -> None:
    response = await post_prepare(
        "option_close",
        "close_intent",
        {
            "raw_text": "我要平仓",
            "quote_content": "",
            "history_messages": [],
            "message_id": "123",
            "trace": [],
            "field_records": {},
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "request": {
            "product": "option_close",
            "node": "close_intent",
            "state": {
                "raw_text": "我要平仓",
                "quote_content": "",
                "history_messages": [],
            },
        },
        "dropped_fields": ["message_id", "trace", "field_records"],
        "conversions": [],
    }


async def test_prepare_404_matches_run_error_shape() -> None:
    response = await post_prepare("swap", "not_registered", {})
    assert response.status_code == 404
    assert response.json() == {
        "product": "swap",
        "node": "not_registered",
        "detail": "Node not registered",
    }


@pytest.mark.parametrize(
    "body",
    [
        {"node": "close_intent", "langfuse_input": {}},
        {
            "product": "option_close",
            "node": "close_intent",
            "langfuse_input": {},
            "unknown": True,
        },
        {
            "product": "option_close",
            "node": "close_intent",
            "langfuse_input": [],
        },
    ],
)
async def test_outer_request_errors_use_fastapi_standard_422(body: dict[str, Any]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/v1/nodes/prepare", json=body)
    assert response.status_code == 422
    assert set(response.json()) == {"detail"}


async def test_recursively_drops_structured_unknowns_but_preserves_open_dicts() -> None:
    response = await post_prepare(
        "main",
        "render",
        {
            "tickers": [
                {
                    "windCode": "00700.HK",
                    "from_goats": True,
                    "legacy": "drop-me",
                }
            ],
            "place_params": {"orderList": [{"business_extension": {"keep": True}}]},
            "api_result": {"backend_extension": {"keep": True}},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request"]["state"]["tickers"] == [
        {"windCode": "00700.HK", "from_goats": True}
    ]
    assert body["request"]["state"]["place_params"]["orderList"][0][
        "business_extension"
    ] == {"keep": True}
    assert body["request"]["state"]["api_result"] == {
        "backend_extension": {"keep": True}
    }
    assert body["dropped_fields"] == ["tickers[0].legacy"]


async def test_json_container_conversion_then_recursive_cleaning() -> None:
    response = await post_prepare(
        "option_close",
        "close_intent",
        {
            "raw_text": "平仓",
            "quote_content": "",
            "history_messages": json.dumps(
                [{"role": "user", "content": "上一轮", "legacy": True}],
                ensure_ascii=False,
            ),
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request"]["state"]["history_messages"] == [
        {"role": "user", "content": "上一轮"}
    ]
    assert body["conversions"] == [
        {
            "field": "history_messages",
            "from_type": "string",
            "to_type": "array",
            "rule": "json_string",
        }
    ]
    assert body["dropped_fields"] == ["history_messages[0].legacy"]


@pytest.mark.parametrize(
    ("field", "annotation_value", "expected", "rule"),
    [
        ("message_id", "123", 123, "integer_string"),
        ("at_bot", " TRUE ", True, "boolean_string"),
        ("at_bot", "false", False, "boolean_string"),
    ],
)
def test_scalar_safe_conversions(
    field: str, annotation_value: str, expected: Any, rule: str
) -> None:
    from app.node_execution.prepare import prepare_state

    async def target(state: dict[str, Any]) -> dict[str, Any]:
        return state

    registration = NodeRegistration(
        "main",
        "target",
        target,
        input_fields=(field,),
    )
    original = {field: annotation_value}
    result = prepare_state(registration, original)

    assert result.state[field] == expected
    assert result.conversions == [
        {
            "field": field,
            "from_type": "string",
            "to_type": "integer" if field == "message_id" else "boolean",
            "rule": rule,
        }
    ]
    assert original == {field: annotation_value}


async def test_union_string_is_not_parsed_when_already_accepted() -> None:
    response = await post_prepare(
        "main",
        "render",
        {"api_result": '{"status":"ok"}'},
    )
    assert response.status_code == 200, response.text
    assert response.json()["request"]["state"]["api_result"] == '{"status":"ok"}'
    assert response.json()["conversions"] == []


@pytest.mark.parametrize(
    ("value", "error_type"),
    [
        ("12x", "int_type"),
        (1.2, "int_type"),
        (None, "int_type"),
    ],
)
async def test_unsafe_integer_values_are_retained_for_correction(
    value: Any, error_type: str
) -> None:
    response = await post_prepare(
        "main",
        "quick_inquiry",
        CONTEXT | {"raw_text": "询价", "message_id": value},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["request"]["state"]["message_id"] == value
    assert body["conversions"] == []
    assert any(
        item["loc"] == ["state", "message_id"] and item["type"] == error_type
        for item in body["detail"]
    )


async def test_invalid_json_and_wrong_null_are_reported_together() -> None:
    response = await post_prepare(
        "option_close",
        "close_intent",
        {
            "raw_text": None,
            "quote_content": "",
            "history_messages": "[invalid",
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["request"]["state"] == {
        "raw_text": None,
        "quote_content": "",
        "history_messages": "[invalid",
    }
    assert body["conversions"] == []
    assert {tuple(item["loc"]) for item in body["detail"]} == {
        ("state", "raw_text"),
        ("state", "history_messages"),
    }


async def test_nested_required_field_is_in_missing_fields_with_path() -> None:
    response = await post_prepare(
        "option_close",
        "close_intent",
        {
            "raw_text": "平仓",
            "quote_content": "",
            "history_messages": [{"content": "上一轮"}],
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["missing_fields"] == ["history_messages[0].role"]
    assert any(
        item["loc"] == ["state", "history_messages", 0, "role"]
        and item["type"] == "missing"
        for item in body["detail"]
    )


async def test_type_errors_and_all_missing_backend_context_are_aggregated() -> None:
    response = await post_prepare(
        "main",
        "quick_inquiry",
        {"raw_text": 9, "message_id": "bad"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["missing_fields"] == [
        "conversation_id",
        "room_id",
        "user_id",
        "message_id",
    ]
    locations = [item["loc"] for item in body["detail"]]
    assert ["state", "raw_text"] in locations
    assert ["state", "message_id"] in locations
    assert all(["state", field] in locations for field in body["missing_fields"])
    assert len({(tuple(item["loc"]), item["type"], item["msg"]) for item in body["detail"]}) == len(
        body["detail"]
    )


def _all_schema_inputs() -> dict[str, dict[str, Any]]:
    agent = {
        **CONTEXT,
        "raw_text": "查询",
        "quote_content": "",
        "quote_appinfo": "app",
        "guid": "guid",
        "operator_user_id": "operator",
        "history_messages": [],
        "input_files": [],
        "conversation_orders": [],
        "error": None,
        "trace": [],
        "tickers": [],
        "candidates": [],
    }
    inquiry = agent | {
        "iq_rfq_data": {},
        "iq_raw_params": {},
        "iq_field_records": {},
        "iq_order_list": [],
        "iq_types": [],
    }
    place_close = agent | {
        "pc_parsed": parse_reference_message("", ""),
        "pc_order_data": [],
        "pc_candidates": {},
        "pc_llm_output": {},
        "pc_close_orders": [],
        "pc_reject_reply": "reason",
        "pc_reject_decision": "reason",
    }
    return {
        "AgentState": agent,
        "InquiryState": inquiry,
        "PlaceCloseState": place_close,
    }


def test_every_registration_prepares_to_an_executor_valid_request() -> None:
    from app.node_execution.prepare import prepare_state

    executor = NodeExecutor(build_registry())
    schema_inputs = _all_schema_inputs()
    assert len(executor.registrations) == 59

    for key, registration in executor.registrations.items():
        original = copy.deepcopy(schema_inputs[registration.input_schema.__name__])
        result = prepare_state(registration, original)
        assert result.detail == [], key
        assert result.missing_fields == [], key
        assert executor.validate(*key, result.state) is not None, key
        assert original == schema_inputs[registration.input_schema.__name__], key


def test_registry_declarations_are_explicit_valid_and_cover_known_dependencies() -> None:
    registrations = {(item.product, item.name): item for item in build_registry()}
    assert len(registrations) == 59
    for key, item in registrations.items():
        assert isinstance(item.input_fields, tuple), key
        assert len(item.input_fields) == len(set(item.input_fields)), key

    expected_subsets = {
        ("option_close", "close_intent"): {
            "raw_text",
            "quote_content",
            "history_messages",
        },
        ("main", "persist"): {
            "trace",
            "message_id",
            "conversation_id",
            "trace_id",
            "product_type",
            "intent",
        },
        ("swap", "swap_place_order"): {
            "raw_text",
            "quote_content",
            "swap_counterparties",
            "conversation_id",
        },
        ("option", "option_intent"): {
            "raw_text",
            "quote_content",
            "history_messages",
            "bot_name",
            "option_counterparties",
        },
        ("option_close", "close_cancel_close"): {
            "raw_text",
            "quote_content",
            "conversation_orders",
        },
        ("main", "instructions"): {
            "sub_instructions",
            "history_messages",
            "conversation_id",
            "message_id",
        },
    }
    for key, expected in expected_subsets.items():
        assert expected <= set(registrations[key].effective_input_fields), key


class _RequiredSchema(TypedDict):
    index: int
    org_str: str


def test_registration_rejects_invalid_field_contracts() -> None:
    async def target(state: dict[str, Any]) -> dict[str, Any]:
        return state

    with pytest.raises(TypeError, match="input_fields"):
        NodeRegistration("main", "missing_declaration", target)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="Duplicate input field"):
        NodeRegistration(
            "main",
            "duplicate",
            target,
            input_fields=("raw_text", "raw_text"),
        )
    with pytest.raises(ValueError, match="Unknown input fields"):
        NodeRegistration(
            "main",
            "unknown",
            target,
            input_fields=("does_not_exist",),
        )
    class _RequiredSchema(TypedDict):
        index: int
        org_str: str

    with pytest.raises(ValueError, match="Required fields not declared"):
        NodeRegistration(
            "main",
            "schema_required",
            target,
            _RequiredSchema,
            input_fields=("index",),
        )
    with pytest.raises(ValueError, match="Required fields not declared"):
        NodeRegistration(
            "main",
            "registration_required",
            target,
            input_fields=(),
            required=("raw_text",),
        )


def test_prompt_and_gray_selection_dependencies_are_registered() -> None:
    registrations = {(item.product, item.name): item for item in build_registry()}
    prompt_dependencies = {
        ("main", "intent_route"): {"raw_text", "quote_content"},
        ("option", "option_intent"): {
            "raw_text",
            "quote_content",
            "history_messages",
            "bot_name",
            "option_counterparties",
        },
        ("option", "inquiry_extract"): {
            "raw_text",
            "quote_content",
            "history_messages",
        },
        ("swap", "swap_intent"): {
            "raw_text",
            "quote_content",
            "swap_counterparties",
            "conversation_id",
        },
        ("swap", "swap_place_order"): {
            "raw_text",
            "quote_content",
            "swap_counterparties",
            "conversation_id",
        },
        ("swap", "swap_recognize_fresh_counterparty"): {
            "raw_text",
            "swap_counterparties",
        },
        ("swap", "swap_select_counterparty"): {
            "raw_text",
            "quote_content",
            "swap_counterparties",
        },
        ("swap", "swap_select_ticker"): {
            "raw_text",
            "quote_content",
            "quote_ticker_candidates",
        },
        ("swap", "swap_image_order"): {
            "conversation_id",
            "swap_counterparties",
            "raw_text",
        },
        ("swap", "swap_excel_order"): {"conversation_id", "raw_text"},
        ("option_close", "close_intent"): {
            "raw_text",
            "quote_content",
            "history_messages",
        },
        ("option_close", "close_holding_query"): {
            "raw_text",
            "option_counterparties",
        },
        ("option_close", "place_close_extract"): {"raw_text", "quote_content"},
    }
    for key, fields in prompt_dependencies.items():
        assert fields <= set(registrations[key].effective_input_fields), key


def test_prepare_does_not_invoke_node() -> None:
    from app.node_execution.prepare import prepare_state

    calls = 0

    async def target(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return state

    registration = NodeRegistration(
        "main",
        "target",
        target,
        input_fields=("raw_text",),
    )
    result = prepare_state(registration, {"raw_text": "hello"})
    assert result.detail == []
    assert calls == 0


def _without_trace_ids(output: dict[str, Any]) -> dict[str, Any]:
    """TraceEntry.id 每次随机、elapsed_ms 随机器抖动（CI 上 0 vs 1 ms），只比较业务内容。"""
    stripped = dict(output)
    stripped["trace"] = [
        {k: v for k, v in entry.items() if k not in ("id", "elapsed_ms")}
        for entry in output.get("trace", [])
    ]
    return stripped


async def test_prompt_input_is_identical_before_and_after_prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.node_execution.prepare import prepare_state
    from app.subgraphs.close.intent import SPEC

    original = {
        "raw_text": "我要平仓",
        "quote_content": "上一轮",
        # 历史消息带显式 id：证据引用键为 history:<id>，随机 id 会让两次校验的提示词不同
        "history_messages": [{"id": "history-1", "role": "user", "content": "查持仓"}],
        "trace": [{"node": "legacy"}],
        "message_id": 99,
    }
    executor = NodeExecutor(build_registry())
    registration = executor.registrations[("option_close", "close_intent")]
    prepared = prepare_state(registration, original)

    before_state = executor.validate("option_close", "close_intent", original)
    after_state = executor.validate("option_close", "close_intent", prepared.state)
    assert SPEC.build_messages(before_state) == SPEC.build_messages(after_state)

    captured: list[Any] = []
    llm = MagicMock()
    reply = intent_reply(CloseIntentOutput, type="close_order_request")

    async def invoke(messages: Any) -> CloseIntentOutput:
        captured.append(messages)
        return reply(messages)

    llm.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=invoke)
    monkeypatch.setattr("app.subgraphs.close.intent.get_qwen_thinking", lambda: llm)
    before = await executor.run("option_close", "close_intent", before_state)
    after = await executor.run("option_close", "close_intent", after_state)
    assert _without_trace_ids(before) == _without_trace_ids(after)
    assert captured[0] == captured[1]


async def test_backend_request_is_identical_before_and_after_prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.node_execution.prepare import prepare_state

    requests: list[dict[str, Any]] = []

    class RecordingClient:
        async def operate(self, req: Any) -> dict[str, Any]:
            requests.append(req.model_dump(mode="json", by_alias=True))
            return {"code": 0, "data": "ok"}

    monkeypatch.setattr(
        "app.subgraphs.option.backend.OptionClientHttpx", lambda: RecordingClient()
    )
    executor = NodeExecutor(build_registry())
    registration = executor.registrations[("option", "option_extract_query")]
    original = CONTEXT | {
        "raw_text": "查询 Q-20260921-1234567890",
        "quote_content": "",
        "quote_appinfo": "app",
        "guid": "guid",
        "operator_user_id": "operator",
        "history_messages": [{"id": "h-2", "role": "user", "content": "unrelated"}],
    }
    prepared = prepare_state(registration, original)

    before_state = executor.validate("option", "option_extract_query", original)
    after_state = executor.validate("option", "option_extract_query", prepared.state)
    before = await executor.run("option", "option_extract_query", before_state)
    after = await executor.run("option", "option_extract_query", after_state)

    assert _without_trace_ids(before) == _without_trace_ids(after)
    assert requests[0] == requests[1]
    assert "history_messages" in original
    assert "history_messages" not in prepared.state


def test_openapi_contains_three_prepare_examples() -> None:
    operation = app.openapi()["paths"]["/v1/nodes/prepare"]["post"]
    examples = operation["requestBody"]["content"]["application/json"]["examples"]
    assert set(examples) == {"normal_pruning", "safe_conversion", "missing_context"}
    success_examples = operation["responses"]["200"]["content"]["application/json"][
        "examples"
    ]
    failure_examples = operation["responses"]["422"]["content"]["application/json"][
        "examples"
    ]
    assert set(success_examples) == {"normal_pruning", "safe_conversion"}
    assert set(failure_examples) == {"missing_context"}


async def test_openapi_prepare_examples_match_runtime_responses() -> None:
    operation = app.openapi()["paths"]["/v1/nodes/prepare"]["post"]
    request_examples = operation["requestBody"]["content"]["application/json"]["examples"]
    response_examples = {
        **operation["responses"]["200"]["content"]["application/json"]["examples"],
        **operation["responses"]["422"]["content"]["application/json"]["examples"],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for name, request_example in request_examples.items():
            response = await client.post("/v1/nodes/prepare", json=request_example["value"])
            expected_status = 422 if name == "missing_context" else 200
            assert response.status_code == expected_status, name
            assert response.json() == response_examples[name]["value"], name
