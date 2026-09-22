"""harness.multi_turn 轮次语义纯函数测试（plan0909 P2）。"""
from __future__ import annotations

from harness.golden import TurnSpec
from harness.multi_turn import (
    _extract_turn,
    early_stop_kind,
    is_unusable_quote,
    quote_for_turn,
)

DEDUP_REPLY = "正在处理，请勿重复提交"


def test_quote_empty_without_previous_context() -> None:
    assert quote_for_turn(0, None, ["r1"]) == ""
    assert quote_for_turn(1, False, ["r1"]) == ""
    assert quote_for_turn(1, True, []) == ""


def test_quote_true_uses_latest_usable_reply() -> None:
    assert quote_for_turn(2, True, ["r1", "r2"]) == "r2"


def test_quote_true_backtracks_over_unusable_reply() -> None:
    assert quote_for_turn(3, True, ["r1", DEDUP_REPLY]) == "r1"
    assert quote_for_turn(2, True, [DEDUP_REPLY, DEDUP_REPLY]) == ""


def test_quote_none_uses_first_turn_reply() -> None:
    assert quote_for_turn(2, None, ["r1", "r2"]) == "r1"


def test_quote_none_empty_when_first_reply_unusable() -> None:
    assert quote_for_turn(1, None, [DEDUP_REPLY]) == ""


def test_is_unusable_quote_length_boundary() -> None:
    assert is_unusable_quote(DEDUP_REPLY)
    assert not is_unusable_quote("x" * 200 + "正在处理")
    assert not is_unusable_quote("")


def test_early_stop_kind_prefers_node_error_and_narrows_int() -> None:
    assert early_stop_kind(True, 50301) == "node_error"
    assert early_stop_kind(True, None) == "node_error"
    assert early_stop_kind(False, 50301) == "business_reject"
    assert early_stop_kind(False, 0) is None
    assert early_stop_kind(False, None) is None
    assert early_stop_kind(False, "50301") is None


def test_turn_outcome_passes_at_bot_through() -> None:
    assert _extract_turn(1, TurnSpec(send_text="x", at_bot=False), "", {}).at_bot is False
    assert _extract_turn(1, TurnSpec(send_text="x", at_bot=True), "", {}).at_bot is True


def test_error_projection_keeps_category_and_parallel_causes():
    from harness.multi_turn import _error_info
    error = {"node": "extract", "type": "EvidenceError", "code": "E2",
             "causes": [{"node": "resolve", "type": "BackendUnreachableError", "code": "E4"}]}
    projected = _error_info(error)
    assert projected["code"] == "E2"
    assert projected["causes"] == error["causes"]


async def test_failed_http_workflow_preserves_structured_node_error():
    import httpx

    from harness.golden import GoldenCase
    from harness.multi_turn import run_case_multi

    def handle(request):
        return httpx.Response(200, json={"data": {"status": "failed", "error": "friendly",
            "outputs": {"error": {"node": "extract", "type": "EvidenceError", "code": "E2"}}}})
    async with httpx.AsyncClient(base_url="http://test.invalid", transport=httpx.MockTransport(handle)) as client:
        result = await run_case_multi(GoldenCase(id="error", category="swap", turns=[TurnSpec(send_text="test")]),
                                     base_url="http://test.invalid", user_id="u", room_id="r", client=client)
    assert result.turns[0].error["code"] == "E2"
    assert result.turns[0].error["node"] == "extract"


async def test_lifecycle_query_uses_actual_order_number_and_wait(monkeypatch):
    import json
    from unittest.mock import AsyncMock

    import httpx

    from harness.golden import normalize_case
    from harness.multi_turn import run_case_multi

    case = normalize_case({"caseNo": "lifecycle", "send_text": "确认撤单", "sub_scenes": [{
        "send_text": "查询 {{previous_order_id}} 状态", "quote_previous": True,
        "wait_before_seconds": 65,
    }]}, origin="fixture.jsonl:1")
    seen = []
    async def prepare(inputs):
        seen.append(dict(inputs))
    def handle(request):
        body = json.loads(request.content)
        assert body["inputs"] == seen[-1]
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {
            "reply_text": "期权平仓订单CO-20260922-1234ABCD：已收到您的撤单请求"}}})
    sleep = AsyncMock()
    monkeypatch.setattr("harness.multi_turn.asyncio.sleep", sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await run_case_multi(case, base_url="http://local.test", user_id="u", room_id="r",
                                     client=client, before_turn=prepare, turn_interval=10)
    assert result.failure is None
    assert seen[-1]["raw_text"] == "查询 CO-20260922-1234ABCD 状态"
    assert seen[-1]["message_content"] == seen[-1]["raw_text"]
    assert result.turns[-1].send_text == seen[-1]["raw_text"]
    sleep.assert_awaited_once_with(65)


async def test_missing_order_reference_stops_before_sending_request():
    import httpx

    from harness.golden import GoldenCase
    from harness.multi_turn import run_case_multi

    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("must not send"))
    )) as client:
        result = await run_case_multi(GoldenCase(id="missing", category="option", turns=[
            TurnSpec(send_text="查询 {{previous_order_id}} 状态")
        ]), base_url="http://local.test", user_id="u", room_id="r", client=client)
    assert result.failure["kind"] == "technical_error"
    assert result.remaining_turns == 1
    assert not result.turns


def test_order_reference_rejects_ambiguous_orders_and_accepts_repeated_same_id():
    import pytest

    from harness.scenario_inputs import resolve_order_reference

    text = "查询 {{previous_order_id}}"
    with pytest.raises(ValueError, match="唯一订单号"):
        resolve_order_reference(text, "Q-20260922-ABC12345 和 Q-20260922-1234ABCD")
    identifier = "CO-20260922-1234ABCD"
    assert resolve_order_reference(text, f"{identifier} 订单 {identifier}") == f"查询 {identifier}"
    assert resolve_order_reference("确认下单", "") == "确认下单"
