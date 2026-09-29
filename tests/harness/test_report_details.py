"""报告必须完整呈现逐轮输入、预期、输出和失败证据。"""
from __future__ import annotations

from harness.cli import _render_markdown
from harness.evaluation import report_case, turn_diffs
from harness.golden import GoldenCase, TurnSpec
from harness.multi_turn import MultiTurnResult, _extract_turn


def sample_report():
    """用数字字符串差异复现有正常回复、无异常但断言失败的情况。"""
    spec = TurnSpec(send_text="限价10", at_bot=True, expected={"limitPrice": 10},
                    response_contains=["限定价格：10"], response_not_contains=["失败"])
    case = GoldenCase(id="price", name="限价参数", category="option", turns=[spec])
    quote = "完整引用内容" * 40 + "引用结尾"
    outputs = {"reply_text": "限定价格：10\n实际回复结尾", "limitPrice": "10"}
    result = MultiTurnResult(case.id, "session", turns=[_extract_turn(1, spec, quote, outputs)])
    return case, result, report_case(case, result, turn_diffs(case, result))


def test_report_keeps_full_quote_and_original_expectations():
    """结果 JSON 自身须足以复核，不能依赖最新数据文件补全历史期望。"""
    case, result, report = sample_report()
    turn = report["turns"][0]
    assert turn.get("quote_content") == result.turns[0].quote_content
    assert turn.get("assertions") == {
        "expected": {"limitPrice": 10}, "response_contains": ["限定价格：10"],
        "response_contains_any": [], "response_not_contains": ["失败"],
    }
    assert report.get("name") == case.name
    assert report.get("expected_output", {}).get("expected") == {"limitPrice": 10}


def test_markdown_exposes_assertion_only_failure_without_truncating_input():
    """异常为空时，字段差异仍须明确显示期望与实际类型。"""
    _, result, report = sample_report()
    markdown = _render_markdown([report])
    for value in ("限价10", result.turns[0].quote_content, "实际回复结尾",
                  '"limitPrice": 10', '"limitPrice": "10"', "字符串", "数值", "字段差异"):
        assert value in markdown


def test_unexecuted_turns_keep_input_expectation_and_stop_reason():
    """早停轮不能从可读报告消失，也不能伪造实际输出。"""
    case = GoldenCase(id="early", category="option", turns=[
        TurnSpec(send_text="首次输入", expected={"intent": "new_inquiry"}),
        TurnSpec(send_text="未执行的确认", expected={"intent": "confirm_order"}),
    ])
    result = MultiTurnResult(case.id, "session", failure={"turn": 1, "kind": "technical_error"},
                             remaining_turns=2)
    report = report_case(case, result, turn_diffs(case, result))
    missing = report.get("unexecuted_turns", [])
    assert len(missing) == 2
    assert missing[1]["assertions"]["expected"]["intent"] == "confirm_order"
    text = _render_markdown([report])
    assert "未执行的确认" in text and "technical_error" in text and "未执行" in text


def test_intent_node_failure_shows_actual_structured_output_and_error():
    """意图节点没有用户回复时也必须可见输出和来源错误。"""
    report = {"case_id": "intent-x", "category": "intent/option_close", "status": "FAIL",
              "passed": False, "failure": None, "turns": [{
                  "turn": 1, "raw": "全部平仓", "reply": "", "diff": [],
                  "assertions": {"expected": {"intent": "close_order_request"}},
                  "outputs": {"intent": None, "error": {"node": "parse_instruction", "code": "E2",
                                                          "message": "字段证据不在指定来源中"}},
                  "error": {"node": "parse_instruction", "code": "E2",
                            "message": "字段证据不在指定来源中"},
              }]}
    markdown = _render_markdown([report])
    assert "全部平仓" in markdown and "close_order_request" in markdown
    assert "parse_instruction" in markdown and "字段证据不在指定来源中" in markdown
    assert '"intent": null' in markdown


def test_sdk_failure_before_first_turn_still_renders_input_and_expectation():
    """SDK 初始化失败的最小报告没有 category，也必须能输出可复核内容。"""
    report = {"case_id": "startup", "status": "FAIL", "passed": False, "turns": [],
              "failure": {"kind": "execution_error", "error": "synthetic unavailable"},
              "input": {"send_text": "启动前输入"},
              "expected_output": {"expected": {"intent": "new_inquiry"}}}
    text = _render_markdown([report])
    assert "启动前输入" in text and "new_inquiry" in text
    assert "synthetic unavailable" in text
