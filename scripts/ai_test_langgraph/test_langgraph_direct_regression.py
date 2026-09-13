from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from langgraph_direct_regression import (
    CaseResult,
    LangGraphClient,
    TurnResult,
    build_case_trace_input,
    build_case_trace_metadata,
    build_case_trace_output,
    build_langfuse_client,
    evaluate_response,
    open_case_trace,
    parse_workflow_response,
    run_case,
)
from regression_support import AssertionResult


class LangGraphClientContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = LangGraphClient(
            base_url="http://127.0.0.1:8000",
            user_id="user-1",
            room_id="room-1",
            bot_name="A股场外交易助手",
            guid="guid-1",
            option_counterparties="[]",
            swap_counterparties="[]",
            timeout=1,
            retries=0,
            throttle_ms=0,
            verify_tls=True,
        )

    def test_build_payload_matches_workflow_run_contract(self) -> None:
        payload = self.client.build_payload(
            "确认下单",
            conversation_id="conversation-1",
            quote_content="上一轮回复",
            at_bot=False,
        )

        self.assertEqual(payload["response_mode"], "blocking")
        self.assertEqual(payload["user"], "conversation-1")
        self.assertNotIn("query", payload)
        self.assertEqual(payload["inputs"]["raw_content"], "确认下单")
        self.assertEqual(payload["inputs"]["quote_content"], "上一轮回复")
        self.assertEqual(payload["inputs"]["conversation_id"], "conversation-1")
        self.assertEqual(payload["inputs"]["userId"], "user-1")
        self.assertNotIn("user_id", payload["inputs"])
        self.assertEqual(payload["inputs"]["at_bot"], "0")

    def test_parse_workflow_response_reads_reply_and_run_id(self) -> None:
        answer, run_id = parse_workflow_response(
            {
                "workflow_run_id": "run-1",
                "data": {
                    "status": "succeeded",
                    "outputs": {"reply_text": "下单信息已确认"},
                },
            }
        )

        self.assertEqual(answer, "下单信息已确认")
        self.assertEqual(run_id, "run-1")

    def test_send_uses_generated_message_id(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({
                    "workflow_run_id": "run-1",
                    "data": {
                        "status": "succeeded",
                        "outputs": {"reply_text": "ok"},
                    },
                }).encode("utf-8")

        def open_langgraph(request: object, **kwargs: object) -> FakeResponse:
            del kwargs
            payload = json.loads(request.data.decode("utf-8"))
            captured["message_id"] = payload["inputs"]["message_id"]
            return FakeResponse()

        with (
            patch("time.time_ns", return_value=123456789),
            patch("urllib.request.urlopen", side_effect=open_langgraph),
        ):
            answer, run_id, _, _ = self.client.send(
                "确认下单", conversation_id="conversation-1"
            )

        self.assertEqual((answer, run_id), ("ok", "run-1"))
        self.assertEqual(captured["message_id"], "123456789")

    def test_send_propagates_case_traceparent(self) -> None:
        captured: dict[str, str | None] = {}

        class FakeResponse:
            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({
                    "workflow_run_id": "run-1",
                    "data": {
                        "status": "succeeded",
                        "outputs": {"reply_text": "ok"},
                    },
                }).encode("utf-8")

        def open_langgraph(request: object, **kwargs: object) -> FakeResponse:
            del kwargs
            captured["traceparent"] = request.get_header("Traceparent")
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=open_langgraph):
            self.client.send(
                "确认下单",
                conversation_id="conversation-1",
                traceparent="00-11111111111111111111111111111111-2222222222222222-01",
            )

        self.assertEqual(
            captured["traceparent"],
            "00-11111111111111111111111111111111-2222222222222222-01",
        )

    def test_parse_workflow_response_rejects_failed_run(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "模型调用失败"):
            parse_workflow_response(
                {
                    "workflow_run_id": "run-2",
                    "data": {
                        "status": "failed",
                        "error": "模型调用失败",
                        "outputs": {},
                    },
                }
            )

    def test_fixture_expected_route_is_checked_against_outputs(self) -> None:
        assertion = evaluate_response(
            "任意回复",
            {"expected": {"product_type": "swap", "intent": "place_order_request"}},
            outputs={"product_type": "option", "intent": "place_order_request"},
        )

        self.assertFalse(assertion.passed)
        self.assertIn("product_type", assertion.failures[0])

    def test_case_trace_uses_task_name_and_case_id(self) -> None:
        captured: dict[str, object] = {}

        class Span:
            trace_id = "1" * 32
            id = "2" * 16

        class Observation:
            def __enter__(self) -> Span:
                return Span()

            def __exit__(self, *args: object) -> None:
                return None

        class Client:
            def start_as_current_observation(self, **kwargs: object) -> Observation:
                captured.update(kwargs)
                return Observation()

            def get_trace_url(self, *, trace_id: str) -> str:
                return f"https://langfuse.test/{trace_id}"

        with open_case_trace(
            Client(),
            task_name="互换回归",
            scenario={
                "name": "互换下单",
                "caseNo": "swap-135",
                "send_text": "第一轮",
                "sub_scenes": [{"send_text": "第二轮"}],
            },
        ) as trace:
            self.assertIsNotNone(trace)
            assert trace is not None
            self.assertEqual(
                trace.traceparent,
                f"00-{'1' * 32}-{'2' * 16}-01",
            )

        self.assertEqual(captured["name"], "互换回归-swap-135")
        self.assertEqual(
            captured["input"],
            {
                "turns": [
                    {
                        "turn": 1,
                        "scene": "主场景",
                        "query": "第一轮",
                        "quote_source": "none",
                    },
                    {
                        "turn": 2,
                        "scene": "子场景1",
                        "query": "第二轮",
                        "quote_source": "main",
                    },
                ]
            },
        )

    def test_case_trace_is_disabled_outside_development(self) -> None:
        self.assertIsNone(
            build_langfuse_client(
                {
                    "ENVIRONMENT": "production",
                    "ENABLE_LANGFUSE": "true",
                    "LANGFUSE_PUBLIC_KEY": "public",
                    "LANGFUSE_SECRET_KEY": "secret",
                }
            )
        )

    def test_multi_turn_case_reuses_case_traceparent(self) -> None:
        traceparents: list[str] = []

        class Client:
            last_outputs = {"product_type": "swap", "intent": "unknown"}

            def send(self, query: str, **kwargs: object) -> tuple[str, str, str, float]:
                del query
                traceparents.append(str(kwargs["traceparent"]))
                return "回复", "run", str(kwargs["conversation_id"]), 0.1

        result = run_case(
            Client(),
            {
                "name": "swap-135",
                "send_text": "第一轮",
                "sub_scenes": [{"send_text": "第二轮"}],
            },
            ignore_leading_mentions=True,
            traceparent="00-11111111111111111111111111111111-2222222222222222-01",
        )

        self.assertTrue(result.passed)
        self.assertEqual(len(traceparents), 2)
        self.assertEqual(len(set(traceparents)), 1)

    def test_case_trace_contains_compact_diagnostics(self) -> None:
        scenario = {
            "name": "swap-135",
            "caseNo": "swap-135",
            "category": "swap/confirm",
            "type": "positive",
            "source": "csv/swap/row135",
            "_source": "tests/fixtures/golden.jsonl",
            "send_text": "第一轮",
            "expected": {"product_type": "swap", "intent": "place_order_request"},
            "sub_scenes": [
                {
                    "scene": "确认下单",
                    "send_text": "确认下单",
                    "quote_previous": True,
                    "expected": {"intent": "confirm_order"},
                },
                {"scene": "查询订单", "send_text": "查询订单", "quote_previous": False},
            ],
        }
        turns = [
            TurnResult(
                scene="主场景",
                query="第一轮",
                answer="订单卡片",
                elapsed=1.2,
                workflow_run_id="run-1",
                assertion=AssertionResult(passed=True),
                outputs={
                    "product_type": "swap",
                    "intent": "place_order_request",
                    "tickers": [{"windCode": "000001.SZ"}],
                    "place_params": {"orderList": [{"quantity": 5000}]},
                },
            ),
            TurnResult(
                scene="确认下单",
                query="确认下单",
                answer="无法确认",
                elapsed=0.8,
                workflow_run_id="run-2",
                assertion=AssertionResult(
                    passed=False,
                    failures=["intent 断言失败：期望 'confirm_order'，实际 'unknown'"],
                ),
                outputs={"product_type": "swap", "intent": "unknown", "tickers": []},
            ),
        ]
        result = CaseResult(
            name="swap-135",
            case_no="swap-135",
            passed=False,
            duration=2.0,
            conversation_id="ai-test-1",
            turns=turns,
        )

        self.assertEqual(
            build_case_trace_metadata("互换回归", scenario),
            {
                "task_name": "互换回归",
                "dataset": "tests/fixtures/golden.jsonl",
                "case_id": "swap-135",
                "case_name": "swap-135",
                "category": "swap/confirm",
                "case_type": "positive",
                "source": "csv/swap/row135",
            },
        )
        trace_input = build_case_trace_input(scenario)
        self.assertEqual(trace_input["turns"][1]["quote_source"], "previous")
        self.assertEqual(trace_input["turns"][2]["quote_source"], "none")
        trace_output = build_case_trace_output(scenario, result)
        self.assertEqual(trace_output["status"], "assertion_failed")
        self.assertEqual(
            trace_output["progress"],
            {"executed": 2, "total": 3, "stopped_early": True},
        )
        self.assertEqual(trace_output["failure"]["turn"], 2)
        self.assertEqual(trace_output["failure"]["kind"], "assertion")
        self.assertEqual(trace_output["turns"][0]["ticker_codes"], ["000001.SZ"])
        self.assertEqual(
            trace_output["turns"][0]["structured_output"],
            {"place_params": {"orderList": [{"quantity": 5000}]}},
        )
        self.assertEqual(trace_output["conversation_id"], "ai-test-1")
        self.assertNotIn("score", trace_output)


if __name__ == "__main__":
    unittest.main()
