"""The real inquiry subgraph verifies raw evidence before normalization or backend IO."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.extraction.candidates import candidate_model
from app.subgraphs.option import extract_inquiry as inquiry
from app.subgraphs.option.models import OptionInquiryRawParams


def setup(monkeypatch, amount="100万"):
    def field(value):
        return {"value": value, "evidence": value, "confidence": .9, "origin": "raw"}

    raw = candidate_model(OptionInquiryRawParams).model_validate({"orderList": [{
        "stockCode": field("甲证券"), "optionType": field("欧式看涨"),
        "tenor": field("1个月"), "strikePercentage": field("80%"),
        "notionalAmount": field(amount),
    }]})
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=raw)
    monkeypatch.setattr(inquiry, "get_qwen_thinking", lambda: llm)
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "BACKEND_CARD"})
    monkeypatch.setattr(inquiry, "call_option_backend", backend)
    return backend


async def test_inquiry_normalizes_only_verified_raw_candidates(monkeypatch):
    backend = setup(monkeypatch)
    result = await inquiry.option_extract_inquiry({"raw_text": "甲证券 欧式看涨 1个月 100万 80%"})
    assert not result.get("error")
    assert backend.await_args.kwargs["order_list"][0]["notionalAmount"] == "1000000"
    record = result["field_records"]["option/inquiry.orderList.0.notionalAmount"]
    assert record.value == "1000000" and record.evidence == "100万" and record.locked
    assert "inquiry_normalize" in [entry.node for entry in result["trace"]]


async def test_inquiry_invented_amount_stops_before_backend(monkeypatch):
    backend = setup(monkeypatch, amount="200万")
    result = await inquiry.option_extract_inquiry({"raw_text": "甲证券 欧式看涨 1个月 100万 80%"})
    assert "evidence" in result["error"].message
    backend.assert_not_awaited()


@pytest.mark.parametrize("explicit_strike", [None, "100", "100call"])
async def test_call_shorthand_reaches_backend_with_verified_strike(monkeypatch, explicit_strike):
    def field(value):
        return {"value": value, "evidence": value, "confidence": .9, "origin": "raw"}

    item = {"stockCode": field("宁德时代"), "optionType": field("100call"), "tenor": field("1M")}
    if explicit_strike is not None:
        item["strikePercentage"] = field(explicit_strike)
    candidates = candidate_model(OptionInquiryRawParams).model_validate({"orderList": [item]})
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=candidates)
    monkeypatch.setattr(inquiry, "get_qwen_thinking", lambda: llm)
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "BACKEND_CARD"})
    monkeypatch.setattr(inquiry, "call_option_backend", backend)

    result = await inquiry.option_extract_inquiry({"raw_text": "宁德时代，100call，1M"})

    assert not result.get("error")
    order = backend.await_args.kwargs["order_list"][0]
    assert order["optionType"] == "欧式看涨"
    assert order["strikePercentage"] == 100.0
    assert order["stockCode"] == "宁德时代"
    record = result["field_records"]["option/inquiry.orderList.0.strikePercentage"]
    assert record.value == 100.0 and record.locked and record.source == "user"
    assert record.evidence == (explicit_strike or "100call")
    if explicit_strike is None:
        assert record.derived_from == ["option/inquiry.orderList.0.optionType"]


async def test_derived_strike_links_to_same_expanded_order(monkeypatch):
    def field(value):
        return {"value": value, "evidence": value, "confidence": .9, "origin": "raw"}

    candidates = candidate_model(OptionInquiryRawParams).model_validate({"orderList": [
        {"stockCode": field("甲证券"), "optionType": field("call"),
         "tenor": field("1M/2M"), "strikePercentage": field("80%")},
        {"stockCode": field("乙证券"), "optionType": field("100call"), "tenor": field("3M")},
    ]})
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=candidates)
    monkeypatch.setattr(inquiry, "get_qwen_thinking", lambda: llm)
    monkeypatch.setattr(inquiry, "call_option_backend", AsyncMock(return_value={"api_code": 0}))

    result = await inquiry.option_extract_inquiry({"raw_text": "甲证券 call 1M/2M 80%；乙证券 100call 3M"})
    assert not result.get("error")
    records = result["field_records"]
    strike = records["option/inquiry.orderList.2.strikePercentage"]
    assert strike.derived_from == ["option/inquiry.orderList.2.optionType"]
    assert records[strike.derived_from[0]].evidence == strike.evidence == "100call"
