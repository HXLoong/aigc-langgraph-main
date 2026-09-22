#!/usr/bin/env python3
"""Regression tests for local LangGraph runner process control."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from functools import lru_cache
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import automation_runner_server as runner  # noqa: E402

from harness.node_annotations import NodeObservation  # noqa: E402
from harness.node_fixtures import NodeFixtureStore  # noqa: E402
from harness.node_runner import NodeRunResult  # noqa: E402
from harness.report_history import HistoricalReportStore  # noqa: E402


class TerminateProcessTests(unittest.TestCase):
    def test_windows_terminates_the_whole_process_tree(self) -> None:
        process = Mock(pid=4321)
        process.poll.return_value = None

        with (
            patch.object(runner.os, "name", "nt"),
            patch.object(runner.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            runner.terminate_process(process)

        run.assert_called_once_with(
            ["taskkill", "/PID", "4321", "/T", "/F"],
            check=False,
            capture_output=True,
        )
        process.terminate.assert_not_called()

    def test_windows_falls_back_when_taskkill_fails(self) -> None:
        process = Mock(pid=4321)
        process.poll.return_value = None

        with (
            patch.object(runner.os, "name", "nt"),
            patch.object(runner.subprocess, "run") as run,
        ):
            run.return_value.returncode = 1
            runner.terminate_process(process)

        process.terminate.assert_called_once_with()


class RunnerCliTests(unittest.TestCase):
    def test_startup_explains_option_position_mock(self) -> None:
        with (
            patch.object(runner, "ThreadingHTTPServer"),
            self.assertLogs(runner.__name__, level="INFO") as logs,
        ):
            self.assertEqual(runner.main(["--no-open"]), 0)

        output = "\n".join(logs.output)
        self.assertIn("GOATS 期权 Mock 服务", output)
        self.assertIn(".venv/bin/python scripts/goats_api_mock/server.py --port 20000", output)
        self.assertIn("GOATS_OPTION_CLOSING_OUT_CONTRACT_QUERY", output)
        self.assertIn("http://127.0.0.1:20000/api/internal/agent/option/position", output)
        for name in ("PLACE_AN_ORDER", "ORDER_QUERY", "ORDER_CANCEL", "ORDER_CANCEL_QUERY"):
            self.assertIn("GOATS_OPTION_CLOSING_OUT_" + name, output)
        self.assertIn("http://127.0.0.1:20000/api/internal/agent/option/order/close/withdrawResult", output)

    def test_host_argument_controls_server_bind_address(self) -> None:
        with (
            patch.object(runner, "ThreadingHTTPServer") as server_class,
            patch.object(runner, "make_handler") as make_handler,
            patch.object(runner.webbrowser, "open") as open_browser,
        ):
            result = runner.main(
                [
                    "--no-open",
                    "--allow-non-dev",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9000",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(server_class.call_args.args[0], ("0.0.0.0", 9000))
        self.assertTrue(make_handler.call_args.kwargs["allow_non_dev"])
        open_browser.assert_not_called()

    def test_allow_non_dev_is_forwarded_to_regression_command(self) -> None:
        job = runner.build_job(
            {
                "dataset": "tests/fixtures/categories/golden_option_close_case.jsonl",
                "run_langgraph": True,
                "push_wecom": False,
                "user_id": "test-user",
                "room_id": "10821094351495088",
                "option_counterparties": "[]",
                "swap_counterparties": "[]",
            },
            allow_non_dev=True,
        )

        self.assertIn("--allow-non-dev", job.commands[0][1])


class RunnerConfigTests(unittest.TestCase):
    def test_default_counterparties_match_dify_workbench(self) -> None:
        with patch.dict(runner.os.environ, {}, clear=True):
            config = runner.build_public_config({})

        option_ids = [item["ctptyId"] for item in json.loads(config["option_counterparties"])]
        swap_ids = [item["ctptyId"] for item in json.loads(config["swap_counterparties"])]
        self.assertEqual(option_ids, [10049, 11125, 15576])
        self.assertEqual(swap_ids, [10049, 11125, 15576, 23971, 16502])

    def test_discovers_langgraph_fixture_datasets(self) -> None:
        datasets = {item["path"]: item["cases"] for item in runner.discover_datasets()}

        self.assertEqual(datasets, {
            str(Path("tests/fixtures/categories") / name): count
            for name, count in {
                "golden_option_close_case.jsonl": 5,
                "golden_option_inquiry_case.jsonl": 4,
                "golden_option_open_case.jsonl": 5,
                "swap_prod_acceptance_data.jsonl": 162,
                "swap_prod_data.jsonl": 123,
                "swap_test_fuzzy_target_recog_data.jsonl": 90,
            }.items()
        })

    def test_fixture_adapter_preserves_quote_semantics(self) -> None:
        cases = runner.load_cases([runner.REPO_ROOT / "tests/fixtures/categories/golden_option_open_case.jsonl"])
        multi_turn = next(case for case in cases if case.get("sub_scenes"))

        self.assertIn("quote_previous", multi_turn["sub_scenes"][0])
        self.assertTrue(multi_turn["category"])
        self.assertTrue(multi_turn["_source"])

    def test_job_passes_task_name_to_case_trace(self) -> None:
        payload = {
            "task_name": "互换回归",
            "dataset": "tests/fixtures/categories/golden_option_close_case.jsonl",
            "run_langgraph": True,
            "push_wecom": False,
            "limit": 1,
            "user_id": "1688857726396147",
            "room_id": "10821094351495088",
            "option_counterparties": "[]",
            "swap_counterparties": "[]",
        }

        job = runner.build_job(payload, job_id="a" * 32)
        command = job.commands[0][1]

        self.assertEqual(command[command.index("--task-name") + 1], "互换回归")

    def test_test_identity_falls_back_to_langgraph_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary = root / "aigc.env"
            fallback = root / "langgraph.env"
            primary.write_text("EVAL_USER_ID=primary-user\n", encoding="utf-8")
            fallback.write_text(
                "EVAL_USER_ID=fallback-user\nEVAL_ROOM_ID=10821094351495088\n",
                encoding="utf-8",
            )

            values = runner.load_runner_config_values(primary, fallback)

        self.assertEqual(values["EVAL_USER_ID"], "primary-user")
        self.assertEqual(values["EVAL_ROOM_ID"], "10821094351495088")


class ChatTurnTests(unittest.TestCase):
    def test_chat_turn_converts_client_build_error(self) -> None:
        with (
            patch.object(
                runner,
                "build_chat_turn",
                side_effect=runner.RegressionRunnerError("缺少有效配置：测试 Token"),
            ),
            self.assertRaisesRegex(runner.RunnerServerError, "缺少有效配置"),
        ):
            runner.send_chat_turn({"query": "测试"})

    def test_free_chat_generates_conversation_and_preserves_quote(self) -> None:
        captured: dict[str, object] = {}

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                captured["client"] = kwargs
                self.last_outputs = {"intent": "swap", "reply_text": "已收到确认"}

            def send(self, query: str, **kwargs: object) -> tuple[str, str, str, float]:
                captured["send"] = {"query": query, **kwargs}
                return "已收到确认", "workflow-run-1", str(kwargs["conversation_id"]), 0.42

        result = runner.send_chat_turn(
            {
                "query": "确认下单",
                "quote_content": "上一轮 LangGraph 回复",
                "at_bot": False,
                "base_url": "http://127.0.0.1:8000",
                "user_id": "self-test-user",
                "room_id": "10821094351495088",
                "option_counterparties": "[]",
                "swap_counterparties": "[]",
                "langgraph_timeout": 120,
                "langgraph_retries": 1,
            },
            dotenv_values={},
            client_factory=FakeClient,
        )

        conversation_id = result["conversation_id"]
        self.assertTrue(str(conversation_id).startswith("ai-test-chat-"))
        self.assertEqual(
            captured["send"],
            {
                "query": "确认下单",
                "conversation_id": conversation_id,
                "quote_content": "上一轮 LangGraph 回复",
                "at_bot": False,
            },
        )
        self.assertEqual(result["answer"], "已收到确认")
        self.assertEqual(result["outputs"]["intent"], "swap")

    def test_chat_http_endpoint_returns_turn_result(self) -> None:
        token = "runner-test-token"
        handler = runner.make_handler({}, [], threading.Condition(), token)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        expected = {
            "answer": "测试回复",
            "conversation_id": "ai-test-chat-1",
            "workflow_run_id": "run-1",
            "duration": 0.1,
            "outputs": {"reply_text": "测试回复"},
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/chat/messages",
            data=json.dumps({"query": "测试"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Runner-Token": token},
            method="POST",
        )
        try:
            with (
                patch.object(runner, "send_chat_turn", return_value=expected),
                urllib.request.urlopen(request, timeout=3) as response,
            ):
                actual = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.assertEqual(actual, expected)


class NodeAnnotationEndpointTests(unittest.TestCase):
    def test_case_nodes_endpoint_explains_missing_langfuse_trace(self) -> None:
        token = "runner-test-token"
        job = runner.Job(
            job_id="0" * 32,
            name="旧报告节点标注测试",
            dataset="test.jsonl",
            config={},
            commands=[],
        )
        job.case_details[1] = {
            "name": "case-old",
            "turns": [{"outputs": {"trace_id": "business-trace"}}],
        }

        def unavailable_loader(_case: dict[str, object]) -> list[object]:
            raise ValueError("该运行没有可用的 Langfuse Trace，请重新执行用例后再标注")

        handler = runner.make_handler(
            {job.job_id: job},
            [job.job_id],
            threading.Condition(),
            token,
            node_loader=unavailable_loader,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/jobs/{job.job_id}/cases/1/nodes",
            headers={"X-Runner-Token": token},
        )
        try:
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=3)
            payload = json.loads(raised.exception.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.assertEqual(raised.exception.code, 422)
        self.assertEqual(
            payload["error"],
            "该运行没有可用的 Langfuse Trace，请重新执行用例后再标注",
        )

    def test_case_nodes_endpoint_returns_normalized_langfuse_nodes(self) -> None:
        token = "runner-test-token"
        job = runner.Job(
            job_id="a" * 32,
            name="节点标注测试",
            dataset="test.jsonl",
            config={},
            commands=[],
        )
        job.case_details[1] = {
            "name": "case-001",
            "turns": [{"outputs": {"langfuse_trace_id": "trace-1"}}],
        }
        jobs = {job.job_id: job}
        node = NodeObservation(
            observation_id="obs-1",
            trace_id="trace-1",
            turn=1,
            name="swap_intent",
            product_type="swap",
            category="意图识别",
            replayable=True,
            side_effect="none",
            input={"raw_text": "确认下单"},
            output={"intent": "confirm_order"},
        )
        handler = runner.make_handler(
            jobs,
            [job.job_id],
            threading.Condition(),
            token,
            node_loader=lambda _case: [node],
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/jobs/{job.job_id}/cases/1/nodes",
            headers={"X-Runner-Token": token},
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                actual = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.assertEqual(actual["nodes"][0]["observation_id"], "obs-1")
        self.assertEqual(actual["nodes"][0]["output"]["intent"], "confirm_order")

    def test_case_nodes_endpoint_uses_configured_langfuse_project(self) -> None:
        token = "runner-test-token"
        job = runner.Job(
            job_id="b" * 32,
            name="节点标注测试",
            dataset="test.jsonl",
            config={},
            commands=[],
        )
        job.case_details[1] = {"name": "case-001", "turns": []}
        node = NodeObservation(
            observation_id="obs-2",
            trace_id="trace-2",
            turn=1,
            name="option_intent",
            product_type="option",
            category="意图识别",
            replayable=True,
            side_effect="none",
        )
        handler = runner.make_handler(
            {job.job_id: job},
            [job.job_id],
            threading.Condition(),
            token,
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/jobs/{job.job_id}/cases/1/nodes",
            headers={"X-Runner-Token": token},
        )
        try:
            with (
                patch.object(runner, "load_case_nodes_from_langfuse", return_value=[node]),
                urllib.request.urlopen(request, timeout=3) as response,
            ):
                actual = json.load(response)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.assertEqual(actual["nodes"][0]["observation_id"], "obs-2")

    def test_node_fixture_endpoint_persists_selected_fields(self) -> None:
        token = "runner-test-token"
        job = runner.Job(
            job_id="c" * 32,
            name="节点标注测试",
            dataset="test.jsonl",
            config={},
            commands=[],
        )
        job.case_details[1] = {
            "name": "case-001",
            "case_no": "case-001",
            "turns": [{"outputs": {"langfuse_trace_id": "trace-1"}}],
        }
        definition = runner.DEFAULT_NODE_REGISTRY["swap_intent"]
        node = NodeObservation(
            observation_id="obs-save",
            trace_id="trace-1",
            turn=1,
            name="swap_intent",
            product_type="swap",
            category="意图识别",
            replayable=True,
            side_effect="none",
            input={"raw_text": "确认下单"},
            output={"intent": "confirm_order"},
        )
        with tempfile.TemporaryDirectory() as directory:
            store = NodeFixtureStore(
                Path(directory), registry={"swap_intent": definition}
            )
            handler = runner.make_handler(
                {job.job_id: job},
                [job.job_id],
                threading.Condition(),
                token,
                node_loader=lambda _case: [node],
                fixture_store=store,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/jobs/{job.job_id}/cases/1/node-fixtures",
                data=json.dumps(
                    {
                        "observation_id": "obs-save",
                        "annotator": "LLW",
                        "mode": "fields",
                        "expected_fields": {"/intent": "confirm_order"},
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Runner-Token": token},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    actual = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

            saved = Path(actual["saved_path"])
            self.assertTrue(saved.is_file())
            record = json.loads(saved.read_text(encoding="utf-8").strip())
            self.assertEqual(record["expected"]["fields"]["/intent"], "confirm_order")

    def test_history_endpoints_support_node_annotation(self) -> None:
        token = "runner-test-token"
        node = NodeObservation(
            observation_id="obs-history",
            trace_id="trace-history",
            turn=1,
            name="option_intent",
            product_type="option",
            category="意图识别",
            replayable=True,
            side_effect="none",
            input={"raw_text": "确认"},
            output={"intent": "confirm_order"},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "reports" / "20260920" / "langgraph-direct-test.json"
            report_path.parent.mkdir(parents=True)
            report_path.write_text(
                json.dumps(
                    {
                        "generated_at": 1_790_000_000,
                        "summary": {"total": 1, "passed": 1, "failed": 0},
                        "cases": [
                            {
                                "case_no": "case-history",
                                "name": "历史用例",
                                "passed": True,
                                "turns": [
                                    {"outputs": {"langfuse_trace_id": "trace-history"}}
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            history = HistoricalReportStore(root / "reports")
            fixture_store = NodeFixtureStore(
                root / "nodes",
                registry={"option_intent": runner.DEFAULT_NODE_REGISTRY["option_intent"]},
            )
            handler = runner.make_handler(
                {},
                [],
                threading.Condition(),
                token,
                node_loader=lambda _case: [node],
                fixture_store=fixture_store,
                history_store=history,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            headers = {"X-Runner-Token": token}
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(f"{base}/api/history", headers=headers),
                    timeout=3,
                ) as response:
                    reports = json.load(response)["reports"]
                report_id = reports[0]["report_id"]
                with urllib.request.urlopen(
                    urllib.request.Request(
                        f"{base}/api/history/{report_id}/cases/1/nodes",
                        headers=headers,
                    ),
                    timeout=3,
                ) as response:
                    nodes = json.load(response)["nodes"]
                request = urllib.request.Request(
                    f"{base}/api/history/{report_id}/cases/1/node-fixtures",
                    data=json.dumps(
                        {
                            "observation_id": "obs-history",
                            "annotator": "LLW",
                            "mode": "fields",
                            "expected_fields": {"/intent": "confirm_order"},
                        }
                    ).encode("utf-8"),
                    headers={**headers, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    saved = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

            self.assertEqual(nodes[0]["observation_id"], "obs-history")
            self.assertTrue(Path(saved["saved_path"]).is_file())


class NodeRegressionEndpointTests(unittest.TestCase):
    def test_node_regression_report_includes_case_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "option_intent.jsonl"
            fixture_path.write_text(
                json.dumps(
                    {
                        "id": "timed-case",
                        "product_type": "option",
                        "node_name": "option_intent",
                        "input": {},
                        "expected": {"mode": "fields", "fields": {"/intent": "new_inquiry"}},
                        "replay": {"enabled": True, "side_effect": "none"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            job = runner.NodeRegressionJob(
                job_id="timed-job",
                fixture_paths=[fixture_path],
                transport="direct",
                base_url="http://127.0.0.1:8000",
                mock_external=False,
                timeout=60,
                api_key="",
                summary={"total": 1, "passed": 0, "failed": 0, "skipped": 0},
            )

            async def run_fixture(*_args: object, **_kwargs: object) -> NodeRunResult:
                return NodeRunResult(
                    fixture_id="timed-case",
                    node_name="option_intent",
                    passed=True,
                    actual={"intent": "new_inquiry"},
                )

            async def close_clients() -> None:
                return None

            with (
                patch.object(runner, "run_node_fixture", run_fixture),
                patch.object(runner, "_close_node_regression_llm_clients", close_clients),
                patch.object(runner.time, "perf_counter", side_effect=[10.0, 11.25]),
            ):
                result = asyncio.run(runner._execute_node_regression_async(job))

        self.assertEqual(result["reports"][0]["duration"], 1.25)

    def test_direct_jobs_do_not_reuse_llm_clients_across_event_loops(self) -> None:
        from app.llm import clients as llm_clients

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_path = root / "option" / "option_intent.jsonl"
            fixture_path.parent.mkdir(parents=True)
            fixture_path.write_text(
                json.dumps(
                    {
                        "id": "loop-bound",
                        "product_type": "option",
                        "node_name": "option_intent",
                        "input": {},
                        "expected": {"mode": "fields", "fields": {"/intent": "new_inquiry"}},
                        "replay": {"enabled": True, "side_effect": "none"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            clients_created: list[object] = []

            class AsyncClient:
                def __init__(self, owner: object) -> None:
                    self.owner = owner

                async def close(self) -> None:
                    self.owner.async_closed = True

            class SyncClient:
                def __init__(self, owner: object) -> None:
                    self.owner = owner

                def close(self) -> None:
                    self.owner.sync_closed = True

            class LoopBoundClient:
                def __init__(self) -> None:
                    self.loop = asyncio.get_running_loop()
                    self.async_closed = False
                    self.sync_closed = False
                    self.root_async_client = AsyncClient(self)
                    self.root_client = SyncClient(self)
                    clients_created.append(self)

            @lru_cache(maxsize=1)
            def loop_bound_client() -> object:
                return LoopBoundClient()

            async def run_fixture(*_args: object, **_kwargs: object) -> NodeRunResult:
                if loop_bound_client().loop is not asyncio.get_running_loop():
                    raise RuntimeError("cached LLM client reused across event loops")
                return NodeRunResult(
                    fixture_id="loop-bound",
                    node_name="option_intent",
                    passed=True,
                    actual={"intent": "new_inquiry"},
                )

            def make_job() -> runner.NodeRegressionJob:
                return runner.build_node_regression_job(
                    {
                        "fixtures": ["option/option_intent.jsonl"],
                        "transport": "direct",
                    },
                    fixture_root=root,
                )

            with (
                patch.object(runner, "run_node_fixture", run_fixture),
                patch.object(llm_clients, "get_qwen_structured", loop_bound_client),
            ):
                first = runner.execute_node_regression(make_job())
                second = runner.execute_node_regression(make_job())

        self.assertEqual(first["summary"]["passed"], 1)
        self.assertEqual(second["summary"]["passed"], 1)
        self.assertTrue(all(client.async_closed for client in clients_created))
        self.assertTrue(all(client.sync_closed for client in clients_created))

    def test_discovers_node_fixture_files_and_nodes_dynamically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            option = root / "option" / "option_intent.jsonl"
            future = root / "future" / "future_node.jsonl"
            option.parent.mkdir(parents=True)
            future.parent.mkdir(parents=True)
            option.write_text(
                json.dumps(
                    {
                        "id": "option-1",
                        "product_type": "option",
                        "node_name": "option_intent",
                        "replay": {"enabled": False, "side_effect": "write"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            future.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "id": f"future-{index}",
                            "product_type": "future_product",
                            "node_name": "future_node",
                            "replay": {
                                "enabled": index == 0,
                                "side_effect": "none" if index == 0 else "write",
                            },
                        }
                    )
                    for index in range(2)
                )
                + "\n",
                encoding="utf-8",
            )

            catalog = runner.discover_node_fixture_files(root)

        self.assertEqual(
            [(item["path"], item["cases"]) for item in catalog],
            [("future/future_node.jsonl", 2), ("option/option_intent.jsonl", 1)],
        )
        self.assertEqual(catalog[0]["nodes"], ["future_node"])
        self.assertEqual(catalog[0]["products"], ["future_product"])
        self.assertEqual(catalog[0]["replayable_cases"], 1)
        self.assertEqual(catalog[0]["annotation_only_cases"], 1)
        self.assertEqual(catalog[1]["replayable_cases"], 0)
        self.assertEqual(catalog[1]["annotation_only_cases"], 1)

    def test_node_regression_job_runs_selected_fixture_and_returns_diffs(self) -> None:
        token = "runner-test-token"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture_path = root / "option" / "option_intent.jsonl"
            fixture_path.parent.mkdir(parents=True)
            fixture_path.write_text(
                json.dumps(
                    {
                        "id": "option-1",
                        "product_type": "option",
                        "node_name": "option_intent",
                        "input": {},
                        "expected": {"mode": "fields", "fields": {"/intent": "new_inquiry"}},
                        "replay": {"enabled": True, "side_effect": "none"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            def execute(task: runner.NodeRegressionJob) -> dict[str, object]:
                self.assertEqual(task.transport, "direct")
                self.assertEqual(task.fixture_paths, [fixture_path.resolve()])
                return {
                    "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0},
                    "reports": [
                        {
                            "fixture_id": "option-1",
                            "node_name": "option_intent",
                            "passed": False,
                            "diffs": [
                                {
                                    "path": "/intent",
                                    "expected": "new_inquiry",
                                    "actual": "unknown",
                                }
                            ],
                        }
                    ],
                }

            handler = runner.make_handler(
                {},
                [],
                threading.Condition(),
                token,
                node_fixture_root=root,
                node_regression_executor=execute,
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            headers = {"X-Runner-Token": token}
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(
                        f"{base}/api/node-regressions/fixtures", headers=headers
                    ),
                    timeout=3,
                ) as response:
                    fixtures = json.load(response)["fixtures"]
                request = urllib.request.Request(
                    f"{base}/api/node-regressions/jobs",
                    data=json.dumps(
                        {
                            "fixtures": ["option/option_intent.jsonl"],
                            "transport": "direct",
                            "mock_external": False,
                        }
                    ).encode("utf-8"),
                    headers={**headers, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    created = json.load(response)
                deadline = time.time() + 3
                detail: dict[str, object] = created
                while detail.get("status") not in {"success", "failed"} and time.time() < deadline:
                    time.sleep(0.02)
                    with urllib.request.urlopen(
                        urllib.request.Request(
                            f"{base}/api/node-regressions/jobs/{created['job_id']}",
                            headers=headers,
                        ),
                        timeout=3,
                    ) as response:
                        detail = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

        self.assertEqual(fixtures[0]["path"], "option/option_intent.jsonl")
        self.assertEqual(detail["status"], "failed")
        self.assertEqual(detail["summary"]["failed"], 1)
        self.assertEqual(detail["reports"][0]["diffs"][0]["path"], "/intent")


class RunnerEncodingTests(unittest.TestCase):
    def test_python_child_events_preserve_chinese_text(self) -> None:
        result = {
            "name": "测试用例一",
            "case_no": "case-1",
            "passed": False,
            "duration": 0.01,
            "error": "断言失败：未找到期望内容",
            "turns": [],
        }
        child_code = (
            "import json\n"
            f"prefix={runner.RUNNER_EVENT_PREFIX!r}\n"
            f"result={result!r}\n"
            "print(prefix+json.dumps({'type':'case_completed','index':1,'total':1,"
            "'result':result},ensure_ascii=False),flush=True)\n"
        )
        job = runner.Job(
            job_id="1" * 32,
            name="编码测试",
            dataset="test.jsonl",
            config={},
            commands=[("编码测试", [sys.executable, "-c", child_code], {})],
            total_cases=1,
        )

        runner.run_job(job, threading.Condition(threading.Lock()))

        self.assertEqual(job.case_details[1]["name"], "测试用例一")
        self.assertEqual(job.case_details[1]["error"], "断言失败：未找到期望内容")


if __name__ == "__main__":
    unittest.main()
