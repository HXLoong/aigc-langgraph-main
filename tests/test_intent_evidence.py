"""联合意图结果必须保留真实置信度和本轮来源，历史不能独立授予执行。"""
from __future__ import annotations

import pytest

from app.subgraphs.option.intent import option_intent
from app.subgraphs.swap.intent import swap_intent


async def test_intent_keeps_verified_confidence_and_source_locations():
    """语义来源在产品图重放时仍逐项检查。"""
    result = await option_intent({"raw_text": "就按这个期限", "quote_content": "询价单请补充期限",
        "history_messages": [{"id": "h-1", "role": "user", "content": "3个月"}],
        "parsed_instruction": {"intent": "place_order_from_quote", "confidence": .87, "evidence": [
            {"text": "就按这个期限", "origin": "raw"}, {"text": "请补充期限", "origin": "quote"},
            {"text": "3个月", "origin": "history", "reference": "history:h-1"}]}})
    assert not result.get("error"), result
    record = result["field_records"]["option/parse.intent"]
    assert record.confidence == .87 and record.value == "place_order_from_quote" and record.locked
    assert result["field_records"]["option/parse.intent.evidence.2"].origin == "history:h-1"


@pytest.mark.parametrize("parsed", [
    {"intent": "place_order_request"},
    {"intent": "place_order_request", "confidence": .99, "evidence": [{"text": "买入一千万", "origin": "raw"}]},
    {"intent": "confirm_order", "confidence": .99, "evidence": [{"text": "确认下单", "origin": "quote"}]},
])
async def test_missing_invented_or_history_only_evidence_stops_execution(parsed):
    """不能凭结构中的意图或高置信度跳过真实来源。"""
    result = await swap_intent({"raw_text": "请处理一下", "quote_content": "确认下单", "parsed_instruction": parsed})
    assert result.get("error") and result["error"].code == "E2"
