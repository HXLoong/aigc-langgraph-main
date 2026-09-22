"""标的识别确定性评估器：逐轮比对 expected.instruments 与 LLM 提取的标的原文 / 交易品种。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from harness.evaluators.instrument_match import evaluate

ROOT = Path(__file__).resolve().parents[1]


def _context(*, expected_output: object, output: object) -> SimpleNamespace:
    return SimpleNamespace(
        experiment=SimpleNamespace(item_expected_output=expected_output),
        observation=SimpleNamespace(output=output),
    )


def _order(code: str, market: str | None = None) -> dict:
    order = {"placeOrderWindCode": code}
    if market:
        order["placeOrderTransactionType"] = market
    return order


def test_instrument_match_accepts_any_expression_and_market_candidate() -> None:
    result = evaluate(
        _context(
            expected_output={
                "expected": {
                    "product_type": "swap",
                    "intent": "place_order_request",
                    "instruments": [
                        {
                            "expression": ["京东"],
                            "transaction_type": ["HK_STOCK", "SH_HK_CONNECT", "SZ_HK_CONNECT"],
                        }
                    ],
                }
            },
            output={
                "turns": [
                    {
                        "product_type": "swap",
                        "place_params": {"orderList": [_order("京东", "SH_HK_CONNECT")]},
                    }
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.name == "det_instrument_match_pass"
    assert score.data_type == "BOOLEAN"
    assert score.value is True
    assert score.metadata == {"assertion_count": 1, "mismatch_count": 0}


def test_instrument_match_is_order_insensitive_and_normalizes_case_and_spaces() -> None:
    result = evaluate(
        _context(
            expected_output={
                "expected": {
                    "instruments": [
                        {"expression": ["NVDA"]},
                        {"expression": ["TSM"]},
                    ]
                }
            },
            output={
                "turns": [
                    {"place_params": {"orderList": [_order("tsm "), _order("NVDA")]}}
                ]
            },
        )
    )

    assert result.scores[0].value is True


def test_instrument_match_reports_missing_and_extra_orders() -> None:
    result = evaluate(
        _context(
            expected_output={
                "expected": {"instruments": [{"expression": ["金力永磁300748.sz", "300748.sz"]}]},
                "sub_scenes": [{"expected": {"instruments": [{"expression": "阿里巴巴"}]}}],
            },
            output={
                "turns": [
                    {"place_params": {"orderList": [_order("300748.SZ"), _order("300748.SZ")]}},
                    {"place_params": {"orderList": [_order("阿里")]}},
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.value is False
    comment = score.comment or ""
    assert "第 1 轮多出标的：300748.SZ" in comment
    assert "第 2 轮未提取到标的：阿里巴巴（实际 阿里）" in comment
    assert score.metadata == {"assertion_count": 2, "mismatch_count": 2}


def test_instrument_match_reports_market_mismatch() -> None:
    result = evaluate(
        _context(
            expected_output={
                "expected": {
                    "instruments": [{"expression": "百济神州", "transaction_type": "A_SHARE"}]
                }
            },
            output={
                "turns": [
                    {"place_params": {"orderList": [_order("百济神州", "HK_STOCK")]}}
                ]
            },
        )
    )

    score = result.scores[0]
    assert score.value is False
    assert "第 1 轮 百济神州 交易品种不符：期望 A_SHARE，实际 HK_STOCK" in (score.comment or "")


def test_instrument_match_reads_snake_case_keys_and_missing_turn() -> None:
    result = evaluate(
        _context(
            expected_output=json.dumps(
                {
                    "expected": {"instruments": [{"expression": "茅台"}]},
                    "sub_scenes": [{"expected": {"instruments": [{"expression": "茅台"}]}}],
                }
            ),
            output=json.dumps(
                {
                    "turns": [
                        {"place_params": {"order_list": [{"place_order_wind_code": "茅台"}]}}
                    ]
                }
            ),
        )
    )

    score = result.scores[0]
    assert score.value is False
    assert "第 2 轮无实际输出" in (score.comment or "")
    assert score.metadata == {"assertion_count": 2, "mismatch_count": 1}


def test_instrument_match_without_instruments_is_a_failure() -> None:
    result = evaluate(
        _context(
            expected_output={"expected": {"product_type": "swap", "intent": "place_order_request"}},
            output={"turns": [{"place_params": {"orderList": [_order("京东")]}}]},
        )
    )

    score = result.scores[0]
    assert score.value is False
    assert "没有可比对的 expected.instruments" in (score.comment or "")


def test_instrument_match_is_registered_as_intent_suite_evaluator() -> None:
    definitions = json.loads(
        (ROOT / "scripts" / "langfuse" / "definitions" / "evaluators.json").read_text(
            encoding="utf-8"
        )
    )
    by_name = {item["name"]: item for item in definitions["evaluators"]}

    assert by_name["instrument-match"]["score_name"] == "det_instrument_match_pass"
    assert by_name["instrument-match"]["suite"] == "intent"
    assert (ROOT / by_name["instrument-match"]["source"]).is_file()
