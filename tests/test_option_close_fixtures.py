"""平仓回归必须保留最终确认覆盖，并为每轮提供可执行的上下文和断言。"""
from __future__ import annotations

import json
from pathlib import Path

DATASET = Path(__file__).parent / "fixtures/categories/golden_option_close_case.jsonl"


def _cases() -> dict[str, dict]:
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    return {row["caseNo"]: row for row in rows}


def test_close_cases_have_per_turn_assertions_and_explicit_quotes() -> None:
    cases = _cases()
    assert set(cases) == {f"case-{n:03d}" for n in range(30, 35)}
    for case in cases.values():
        for index, turn in enumerate([case, *case["sub_scenes"]]):
            assert turn["expected"]["product_type"] == "option_close"
            assert turn["expected"]["intent"].startswith("close_order_")
            assert isinstance(turn["response_contains"], list) and turn["response_contains"]
            assert all("[第" not in value for value in turn["response_contains"])
            assert turn["quote_previous"] is (index > 0)


def test_close_cases_retain_confirmation_and_cancel_coverage() -> None:
    cases = _cases()
    for case_id in ("case-030", "case-031", "case-034"):
        turns = cases[case_id]["sub_scenes"]
        confirmation = next(turn for turn in turns if turn["send_text"] == "确认平仓")
        assert confirmation["expected"]["intent"] == "close_order_confirm"
        assert {"期权平仓订单", "已收到您的下单请求"} <= set(confirmation["response_contains"])
    cancel = cases["case-034"]["sub_scenes"][-2:]
    assert [turn["send_text"] for turn in cancel] == ["撤单", "确认撤单"]
    assert cancel[-1]["expected"]["intent"] == "close_order_cancel_confirm"
    assert all(turn["send_text"] != "确认下单" for turn in cases["case-034"]["sub_scenes"])


def test_sequence_selection_and_small_position_have_required_context() -> None:
    cases = _cases()
    assert cases["case-033"]["send_text"] == "查持仓"
    assert cases["case-033"]["sub_scenes"][0]["send_text"] == "序号2，市价，110万"
    small = cases["case-032"]["sub_scenes"]
    assert [turn["send_text"] for turn in small] == ["第三笔，全平", "POV9", "全部平仓"]
    assert "只能全部平仓" in small[1]["response_contains"]
    assert "平仓名义本金：1,000,000" in small[-1]["response_contains"]


def test_twap_duration_is_clarified_before_final_confirmation() -> None:
    turns = _cases()["case-034"]["sub_scenes"]
    assert "TWAP30分钟" in turns[0]["send_text"]
    assert "起止时间" in turns[0]["response_contains"]
    assert turns[1]["send_text"] == "200万，TWAP18:00-18:30，限价10"
    assert {"起始时间：18:00", "结束时间：18:30"} <= set(turns[1]["response_contains"])
