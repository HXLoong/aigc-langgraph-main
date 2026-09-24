"""完整交易用例必须查询本次订单终态，不能把受理回复当成撤单成功。"""
from pathlib import Path

from harness.golden import load_golden


def test_option_lifecycle_cases_cover_final_confirmation_and_cancel():
    cases = {case.id: case for case in load_golden(Path("tests/fixtures/categories"))}
    for case_id, product, intents in (
        ("case-029-lifecycle", "option",
         ["confirm_order", "request_cancel_order", "confirm_cancel_order", "query_order_status"]),
        ("case-034-lifecycle", "option_close",
         ["close_order_confirm", "close_order_cancel_request", "close_order_cancel_confirm",
          "close_order_order_query"]),
    ):
        assert case_id in cases
        turns = cases[case_id].turns
        assert len(turns) == (7 if product == "option_close" else 6)
        if product == "option_close":
            assert turns[0].expected["intent"] == "close_order_query"
            assert "{{previous_holding_contract_id:1}}" in turns[1].send_text
        assert [turn.expected["intent"] for turn in turns[-4:]] == intents
        assert all(turn.expected["product_type"] == product for turn in turns)
        assert all(turn.response_contains for turn in turns)
        assert "{{previous_order_id}}" in turns[-1].send_text
        assert "已撤单" in turns[-1].response_contains
        assert "撤单中" in turns[-1].response_not_contains
        assert turns[-1].wait_before_seconds >= 65
