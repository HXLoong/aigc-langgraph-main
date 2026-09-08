from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from langgraph_direct_regression import (
    LangGraphClient,
    evaluate_response,
    parse_workflow_response,
)


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


if __name__ == "__main__":
    unittest.main()
