from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest


def _candidate(value: str, evidence: str | None = None) -> dict:
    return {
        "value": value,
        "evidence": evidence or value,
        "confidence": 1.0,
        "origin": "raw",
        "reference": None,
    }


def _swap_place_order_mock_fixture() -> dict:
    return {
        "schema_version": 1,
        "id": "swap-place-order-pilot",
        "product_type": "swap",
        "node_name": "swap_place_order",
        "input": {
            "raw_text": "聚鸣价值精选长飞光纤清仓 市价跟量9%",
            "quote_content": "",
            "swap_counterparties": [
                {
                    "ctptyId": 23971,
                    "shortName": "聚鸣价值精选",
                    "longName": "聚鸣价值精选私募证券投资基金",
                    "sort": "D",
                }
            ],
            "conversation_id": "node-pilot",
        },
        "expected": {
            "mode": "fields",
            "fields": {
                "/expected_action": "place",
                "/place_params/orderList/0/placeOrderWindCode": "长飞光纤",
                "/place_params/orderList/0/placeOrderPriceType": "MarketOrder",
                "/place_params/orderList/0/placeOrderAlgorithmType": "POV",
                "/place_params/orderList/0/placeOrderPovPercent": 9,
                "/place_params/orderList/0/placeOrderCloseIntent": True,
            },
        },
        "replay": {"enabled": True, "side_effect": "read"},
        "mocks": {
            "llm_output": {
                "orderList": [
                    {
                        "placeOrderWindCode": _candidate("长飞光纤"),
                        "placeOrderPriceType": _candidate("市价"),
                        "placeOrderAlgorithmType": _candidate("跟量"),
                        "placeOrderPovPercent": _candidate("9", "9%"),
                        "placeOrderShortname": _candidate("聚鸣价值精选"),
                        "placeOrderEntrustRatio": _candidate("清仓"),
                        "placeOrderCloseIntent": _candidate("清仓"),
                    }
                ]
            },
        },
    }


@pytest.mark.asyncio
async def test_run_node_fixture_executes_only_the_registered_node() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY
    from harness.node_runner import run_node_fixture

    fixture = {
        "schema_version": 1,
        "id": "option-intent-confirm",
        "product_type": "option",
        "node_name": "option_intent",
        "input": {
            "raw_text": "确认下单",
            "quote_content": "",
            "history_messages": [],
        },
        "expected": {
            "mode": "fields",
            "fields": {"/intent": "confirm_order"},
        },
        "replay": {"enabled": True, "side_effect": "none"},
    }

    result = await run_node_fixture(fixture, registry=DEFAULT_NODE_REGISTRY)

    assert result.passed is True
    assert result.node_name == "option_intent"
    assert result.actual["intent"] == "confirm_order"
    assert result.diffs == []


@pytest.mark.asyncio
async def test_run_swap_place_order_fixture_with_mocked_external_dependencies() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY
    from harness.node_runner import run_node_fixture

    try:
        result = await run_node_fixture(
            _swap_place_order_mock_fixture(),
            registry=DEFAULT_NODE_REGISTRY,
            mock_external=True,
        )
    except TypeError as exc:
        pytest.fail(f"节点 runner 尚未支持 mock 模式：{exc}")

    assert result.passed is True
    order = result.actual["place_params"]["orderList"][0]
    assert order["placeOrderWindCode"] == "长飞光纤"
    assert order["placeOrderPovPercent"] == 9


@pytest.mark.asyncio
async def test_run_node_fixture_never_executes_write_node() -> None:
    from harness.node_annotations import NodeDefinition
    from harness.node_runner import NodeRunnerError, run_node_fixture

    definition = NodeDefinition(
        name="dangerous_write",
        product_type="swap",
        category="后端写入",
        replayable=False,
        side_effect="write",
        output_fields=("api_code",),
        callable_path="builtins:print",
    )
    fixture = {
        "id": "write-1",
        "node_name": "dangerous_write",
        "input": {},
        "expected": {"mode": "fields", "fields": {"/api_code": 0}},
        "replay": {"enabled": True, "side_effect": "write"},
    }

    with pytest.raises(NodeRunnerError, match="写副作用"):
        await run_node_fixture(fixture, registry={definition.name: definition})


@pytest.mark.asyncio
async def test_disabled_future_node_fixture_skips_without_registry_entry() -> None:
    from harness.node_runner import NodeFixtureSkipError, run_node_fixture

    fixture = {
        "id": "future-node-1",
        "node_name": "future_node",
        "input": {},
        "expected": {"mode": "fields", "fields": {"/result": "ok"}},
        "replay": {"enabled": False, "side_effect": "unknown"},
    }

    with pytest.raises(NodeFixtureSkipError, match="禁止回放"):
        await run_node_fixture(fixture, registry={})


def test_load_node_fixtures_reads_jsonl_files_recursively(tmp_path) -> None:
    from harness.node_runner import load_node_fixtures

    root = tmp_path / "nodes"
    path = root / "option" / "option_intent.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"id": "fixture-1", "node_name": "option_intent"}) + "\n",
        encoding="utf-8",
    )

    fixtures = load_node_fixtures([root])

    assert fixtures == [{"id": "fixture-1", "node_name": "option_intent"}]


def test_node_run_cli_executes_fixture_file(tmp_path, capsys) -> None:
    from harness.cli import main

    path = tmp_path / "option_intent.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "option-intent-confirm",
                "product_type": "option",
                "node_name": "option_intent",
                "input": {
                    "raw_text": "确认下单",
                    "quote_content": "",
                    "history_messages": [],
                },
                "expected": {
                    "mode": "fields",
                    "fields": {"/intent": "confirm_order"},
                },
                "replay": {"enabled": True, "side_effect": "none"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["node-run", "--data", str(path)])

    assert exit_code == 0
    assert "[PASS] option-intent-confirm (option_intent)" in capsys.readouterr().out


def test_node_run_cli_supports_mock_mode_for_swap_place_order(tmp_path, capsys) -> None:
    from harness.cli import main

    path = tmp_path / "swap_place_order.jsonl"
    report_path = tmp_path / "report.json"
    path.write_text(
        json.dumps(_swap_place_order_mock_fixture(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    try:
        exit_code = main(
            [
                "node-run",
                "--data",
                str(path),
                "--mock",
                "--out",
                str(report_path),
            ]
        )
    except SystemExit as exc:
        pytest.fail(f"node-run 尚未支持 --mock：{exc}")
    except TypeError as exc:
        pytest.fail(f"mock 节点报告不是合法 JSON：{exc}")

    assert exit_code == 0
    assert "[PASS] swap-place-order-pilot (swap_place_order)" in capsys.readouterr().out
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"] == {"total": 1, "passed": 1, "failed": 0}
    assert (
        report["reports"][0]["actual"]["place_params"]["orderList"][0]["placeOrderWindCode"]
        == "长飞光纤"
    )


def test_node_run_cli_skips_non_replayable_fixtures(tmp_path, capsys) -> None:
    from harness.cli import main

    path = tmp_path / "write_nodes.jsonl"
    report_path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "swap-confirm-write",
                "product_type": "swap",
                "node_name": "swap_confirm",
                "input": {},
                "expected": {"mode": "fields", "fields": {"/api_code": 0}},
                "replay": {"enabled": False, "side_effect": "write"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(["node-run", "--data", str(path), "--out", str(report_path)])

    assert exit_code == 0
    assert "[SKIP] swap-confirm-write (swap_confirm)" in capsys.readouterr().out
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"] == {"total": 1, "passed": 0, "failed": 0, "skipped": 1}
    assert report["reports"][0]["skipped"] is True


def test_all_replayable_registry_nodes_have_callable_paths() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY

    missing = [
        definition.name
        for definition in DEFAULT_NODE_REGISTRY.values()
        if definition.replayable and not definition.callable_path
    ]

    assert missing == []


@pytest.mark.asyncio
async def test_run_node_fixture_http_prepares_and_runs_through_external_api() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY
    from harness.node_runner import run_node_fixture_http

    requests: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.method, request.url.path, body))
        assert request.headers["X-Node-Run-Key"] == "test-key"
        if request.url.path.endswith("/prepare"):
            return httpx.Response(
                200,
                json={
                    "request": {
                        "product": "main",
                        "node": "ingest",
                        "state": body["langfuse_input"],
                    },
                    "dropped_fields": [],
                    "conversions": [],
                },
            )
        return httpx.Response(
            200,
            json={
                "product": "main",
                "node": "ingest",
                "output": {"reply_text": None},
            },
        )

    fixture = {
        "id": "ingest-http",
        "product_type": "common",
        "node_name": "ingest",
        "input": {"room_id": "room-1", "trace_id": "trace-1"},
        "expected": {"mode": "fields", "fields": {"/reply_text": None}},
        "replay": {"enabled": True, "side_effect": "none"},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://node-api",
    ) as client:
        result = await run_node_fixture_http(
            fixture,
            registry=DEFAULT_NODE_REGISTRY,
            client=client,
            api_key="test-key",
        )

    assert result.passed is True
    assert [(method, path) for method, path, _ in requests] == [
        ("POST", "/v1/nodes/prepare"),
        ("POST", "/v1/nodes/run"),
    ]
    assert requests[0][2]["product"] == "main"


@pytest.mark.asyncio
async def test_run_node_fixture_http_reports_transport_errors() -> None:
    from harness.node_registry import DEFAULT_NODE_REGISTRY
    from harness.node_runner import NodeRunnerError, run_node_fixture_http

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    fixture = {
        "id": "ingest-http",
        "product_type": "common",
        "node_name": "ingest",
        "input": {"room_id": "room-1", "trace_id": "trace-1"},
        "expected": {"mode": "fields", "fields": {"/reply_text": None}},
        "replay": {"enabled": True, "side_effect": "none"},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://node-api",
    ) as client:
        with pytest.raises(NodeRunnerError, match="节点接口连接失败"):
            await run_node_fixture_http(
                fixture,
                registry=DEFAULT_NODE_REGISTRY,
                client=client,
                api_key="test-key",
            )


def test_node_run_cli_supports_authenticated_http_transport(
    tmp_path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harness import cli
    from harness.node_runner import NodeRunResult

    path = tmp_path / "ingest.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "ingest-http",
                "product_type": "common",
                "node_name": "ingest",
                "input": {"room_id": "room-1", "trace_id": "trace-1"},
                "expected": {"mode": "fields", "fields": {"/reply_text": None}},
                "replay": {"enabled": True, "side_effect": "none"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    run_http = AsyncMock(
        return_value=NodeRunResult(
            fixture_id="ingest-http",
            node_name="ingest",
            passed=True,
            actual={"reply_text": None},
        )
    )
    monkeypatch.setattr(cli, "run_node_fixture_http", run_http, raising=False)
    monkeypatch.setenv("NODE_RUN_API_KEY", "test-key")

    exit_code = cli.main(
        [
            "node-run",
            "--data",
            str(path),
            "--transport",
            "http",
            "--base-url",
            "http://node-api",
        ]
    )

    assert exit_code == 0
    assert "[PASS] ingest-http (ingest)" in capsys.readouterr().out
    assert run_http.await_count == 1
    assert run_http.await_args.kwargs["api_key"] == "test-key"
