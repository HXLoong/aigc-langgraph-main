"""从 categories 业务集派生意图集草稿：只搬路由/意图标签，不搬卡片断言，不猜标签。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import derive_intent_fixtures as derive


def _close_case() -> dict:
    return {
        "caseNo": "case-030",
        "name": "case-030",
        "category": "option_close_case",
        "description": "查持仓后第一笔限价全平并确认",
        "send_text": "我想平仓",
        "at_bot": True,
        "quote_previous": False,
        "expected": {"product_type": "option_close", "intent": "close_order_query"},
        "response_not_contains": ["交易指令服务暂不可用"],
        "sub_scenes": [
            {
                "scene": "第一笔限价全平",
                "send_text": "第一笔，限价10，全平",
                "at_bot": False,
                "quote_previous": True,
                "expected": {"product_type": "option_close", "intent": "close_order_request"},
                "response_not_contains": ["互换订单"],
            }
        ],
        "source": "workbench_fixture",
    }


def test_derive_keeps_labels_and_drops_text_assertions() -> None:
    case = derive.derive_case(_close_case(), source_stem="golden_option_close_case")

    assert case["caseNo"] == "intent-option_close-case-030"
    assert case["category"] == "intent/option_close"
    assert case["type"] == "positive"
    assert case["source"] == "derived:golden_option_close_case#case-030"
    assert case["send_text"] == "我想平仓"
    assert case["at_bot"] is True
    assert case["expected"] == {"product_type": "option_close", "intent": "close_order_query"}
    assert case["sub_scenes"] == [
        {
            "scene": "第一笔限价全平",
            "send_text": "第一笔，限价10，全平",
            "at_bot": False,
            "quote_previous": True,
            "expected": {"product_type": "option_close", "intent": "close_order_request"},
        }
    ]
    assert "response_not_contains" not in case
    assert "review" not in case


def test_derive_fills_product_type_from_category_and_marks_unlabeled_turns() -> None:
    raw = {
        "caseNo": "ai_trade_assist_prod_swap_order_case_1",
        "name": "生产互换下单1",
        "category": "swap_prod_data",
        "send_text": "新增指令：标的：NVDA…",
        "at_bot": True,
        "response_contains": "-----场外收益互换详情-----",
        "sub_scenes": [{"send_text": "确认下单", "at_bot": False, "quote_previous": True}],
    }
    case = derive.derive_case(raw, source_stem="swap_prod_data")

    assert case["caseNo"] == "intent-swap-ai_trade_assist_prod_swap_order_case_1"
    assert case["expected"] == {"product_type": "swap", "intent": ""}
    assert case["sub_scenes"][0]["expected"] == {"product_type": "swap", "intent": ""}
    assert case["review"] == {"status": "pending", "unlabeled_turns": [1, 2]}
    assert "response_contains" not in case


def test_derive_product_type_prefers_existing_label_and_infers_by_prefix() -> None:
    assert derive.product_type_for("option_close_case", {}) == "option_close"
    assert derive.product_type_for("option_inquiry_case", {}) == "option"
    assert derive.product_type_for("swap_test_fuzzy_target_recog_data", {}) == "swap"
    assert derive.product_type_for("swap_prod_data", {"product_type": "unknown"}) == "unknown"


def test_derive_negative_type_is_kept() -> None:
    raw = {**_close_case(), "type": "negative"}
    assert derive.derive_case(raw, source_stem="x")["type"] == "negative"


def test_write_drafts_groups_by_product_and_can_filter_labeled(tmp_path: Path) -> None:
    source = tmp_path / "categories"
    source.mkdir()
    swap = {
        "caseNo": "s1",
        "name": "s1",
        "category": "swap_prod_data",
        "send_text": "买入",
        "at_bot": True,
        "response_contains": "x",
    }
    (source / "golden_option_close_case.jsonl").write_text(
        json.dumps(_close_case(), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (source / "swap_prod_data.jsonl").write_text(
        json.dumps(swap, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    out = tmp_path / "drafts"
    summary = derive.write_drafts(source, out, only_labeled=False)
    assert summary == {"option_close": 1, "swap": 1}
    assert (out / "option_close.jsonl").is_file()
    swap_records = [
        json.loads(line) for line in (out / "swap.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert swap_records[0]["review"]["status"] == "pending"

    seeds = tmp_path / "seeds"
    summary = derive.write_drafts(source, seeds, only_labeled=True)
    assert summary == {"option_close": 1}
    assert not (seeds / "swap.jsonl").exists()
