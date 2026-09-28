"""意图集本地确定性评分：不依赖 Langfuse / Java / GOATS，可在 CI 里给出退出码。"""

from __future__ import annotations

import json
from pathlib import Path

from harness.golden import GoldenCase, TurnSpec, dataset_expected, dataset_input, load_golden
from scripts.langfuse.langfuse_eval import _LocalItem


def _instrument_case() -> GoldenCase:
    return GoldenCase(
        id="intent-swap-instrument-1",
        category="intent/swap",
        turns=[
            TurnSpec(
                send_text="港股市价买一百万京东",
                at_bot=True,
                expected={
                    "product_type": "swap",
                    "intent": "place_order_request",
                    "instruments": [{"expression": ["京东"], "transaction_type": ["HK_STOCK"]}],
                },
            )
        ],
        expected={"product_type": "swap", "intent": "place_order_request"},
    )


def test_dataset_shape_helpers_live_in_harness() -> None:
    """上传脚本与本地评分共用同一份 biz 结构投影。"""
    case = GoldenCase(
        id="c",
        category="intent/option_close",
        turns=[
            TurnSpec(send_text="我想平仓", at_bot=True, expected={"product_type": "option_close", "intent": "close_order_query"}),
            TurnSpec(send_text="确认平仓", quote_previous=True, expected={"intent": "close_order_confirm"}, response_not_contains=["互换订单"]),
        ],
    )
    assert dataset_input(case) == {
        "send_text": "我想平仓",
        "at_bot": True,
        "sub_scenes": [{"send_text": "确认平仓", "at_bot": False, "quote_previous": True}],
    }
    assert dataset_expected(case) == {
        "expected": {"product_type": "option_close", "intent": "close_order_query"},
        "sub_scenes": [{"expected": {"intent": "close_order_confirm"}, "response_not_contains": ["互换订单"]}],
    }


def test_local_item_carries_structured_expected_for_code_evaluators() -> None:
    item = _LocalItem(_instrument_case(), suite="intent")
    assert item.expected_structured == dataset_expected(_instrument_case())
    assert item.has_instruments is True
    assert _LocalItem(GoldenCase(id="x", category="intent/swap", turns=[TurnSpec(send_text="x")])).has_instruments is False


def test_frozen_context_round_trips_through_loader_and_dataset_projection(tmp_path: Path) -> None:
    fixture = tmp_path / "option_close.jsonl"
    row = {
        "caseNo": "intent-option_close-1",
        "category": "intent/option_close",
        "type": "positive",
        "send_text": "我想平仓",
        "at_bot": True,
        "expected": {"product_type": "option_close", "intent": "close_order_query"},
        "sub_scenes": [
            {
                "send_text": "确认平仓",
                "quote_content": "单号：CO-20260506-DEAF117C 请引用本消息回复【确认平仓】",
                "history": [{"role": "assistant", "content": "以下是您的期权持仓："}],
                "prev_product_type": "option_close",
                "expected": {"product_type": "option_close", "intent": "close_order_confirm"},
            }
        ],
    }
    fixture.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    (case,) = load_golden([fixture])
    turn = case.turns[1]
    assert turn.quote_content.startswith("单号：CO-20260506-DEAF117C")
    assert turn.history == [{"role": "assistant", "content": "以下是您的期权持仓："}]
    assert turn.prev_product_type == "option_close"
    assert case.turns[0].quote_content == "" and case.turns[0].history == []

    projected = dataset_input(case)["sub_scenes"][0]
    assert projected["quote_content"] == turn.quote_content
    assert projected["history"] == turn.history
    assert projected["prev_product_type"] == "option_close"
    assert not {"quote_content", "history", "prev_product_type"} & set(dataset_input(case)), "empty context stays out"

    local = _LocalItem(case, suite="intent").input["turns"][1]
    assert (local["quote_content"], local["history"], local["prev_product_type"]) == (
        turn.quote_content, turn.history, "option_close"
    )


