"""LLM intent decisions require source evidence; deterministic rules remain model free."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.extraction.fields import EvidenceError
from app.subgraphs.option import intent as option
from app.subgraphs.swap import intent as swap


def model_reply(monkeypatch, module, factory, payload):
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=payload)
    monkeypatch.setattr(module, factory, lambda: model)
    return model


async def test_model_intent_records_verified_confidence_and_quote_history(monkeypatch):
    model_reply(monkeypatch, option, "get_qwen_structured", {
        "type": "place_order_from_quote", "confidence": 0.87, "evidence": [
            {"text": "就按这个期限", "origin": "raw"},
            {"text": "请补充期限", "origin": "quote"},
            {"text": "3个月", "origin": "history", "reference": "h-1"}]})
    result = await option.option_intent({"raw_text": "就按这个期限", "quote_content": "询价单请补充期限",
        "history_messages": [{"id": "h-1", "role": "user", "content": "3个月"}]})
    assert result.get("error") is None
    assert result["intent"] == "place_order_from_quote"
    record = result["field_records"]["option/intent"]
    assert record.confidence == 0.87 and record.value == "place_order_from_quote"
    assert record.locked
    assert result["field_records"]["option/intent.evidence.2"].origin == "history:h-1"


async def test_type_only_model_output_is_rejected(monkeypatch):
    model_reply(monkeypatch, swap, "get_qwen_thinking", {"type": "place_order_request"})
    with pytest.raises(ValidationError):
        await swap.swap_intent({"raw_text": "来点这个"})


async def test_invented_source_evidence_is_rejected(monkeypatch):
    model_reply(monkeypatch, swap, "get_qwen_thinking", {
        "type": "place_order_request", "confidence": 0.99,
        "evidence": [{"text": "买入一千万", "origin": "raw"}]})
    with pytest.raises(EvidenceError):
        await swap.swap_intent({"raw_text": "来点这个"})


async def test_model_cannot_use_only_old_confirmation_as_current_instruction(monkeypatch):
    model_reply(monkeypatch, swap, "get_qwen_thinking", {
        "type": "confirm_order", "confidence": 0.99,
        "evidence": [{"text": "确认下单", "origin": "quote"}]})
    with pytest.raises(EvidenceError):
        await swap.swap_intent({"raw_text": "好的", "quote_content": "确认下单"})


async def test_deterministic_confirmation_does_not_request_confidence_from_model(monkeypatch):
    model = model_reply(monkeypatch, option, "get_qwen_structured", {})
    result = await option.option_intent({"raw_text": "确认下单"})
    assert result["intent"] == "confirm_order"
    model.with_structured_output.assert_not_called()
    assert not result.get("field_records")


@pytest.mark.parametrize("raw,expected", [("查询持仓", "close_order_query"), ("不要确认撤单", "unknown_intent")])
async def test_close_rule_hit_is_also_model_free(monkeypatch, raw, expected):
    from app.subgraphs.close import intent as close
    model = model_reply(monkeypatch, close, "get_qwen_thinking", {})
    result = await close.close_intent({"raw_text": raw})
    assert result["intent"] == expected
    model.with_structured_output.assert_not_called()
    assert not result.get("field_records")
