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
