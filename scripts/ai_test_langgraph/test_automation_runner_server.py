#!/usr/bin/env python3
"""Regression tests for local LangGraph runner process control."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import automation_runner_server as runner  # noqa: E402


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


class RunnerConfigTests(unittest.TestCase):
    def test_discovers_langgraph_fixture_datasets(self) -> None:
        datasets = {item["path"]: item["cases"] for item in runner.discover_datasets()}

        self.assertEqual(datasets["tests\\fixtures\\golden.jsonl"], 535)
        self.assertEqual(
            datasets["tests\\fixtures\\golden_ticker_2026-05.jsonl"],
            34,
        )
        self.assertTrue(all(path.startswith("tests\\fixtures\\") for path in datasets))

    def test_fixture_adapter_preserves_quote_semantics(self) -> None:
        cases = runner.load_cases([runner.REPO_ROOT / "tests/fixtures/golden.jsonl"])
        multi_turn = next(case for case in cases if case.get("sub_scenes"))

        self.assertIn("quote_previous", multi_turn["sub_scenes"][0])
        self.assertTrue(multi_turn["category"])
        self.assertTrue(multi_turn["source"])

    def test_job_passes_task_name_to_case_trace(self) -> None:
        payload = {
            "task_name": "互换回归",
            "dataset": "tests/fixtures/golden.jsonl",
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
