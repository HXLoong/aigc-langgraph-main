"""The real inquiry subgraph verifies raw evidence before normalization or backend IO."""
from unittest.mock import AsyncMock, MagicMock

from app.extraction.candidates import candidate_model
from app.graph.state import TickerCandidate
from app.subgraphs.option import extract_inquiry as inquiry
from app.subgraphs.option.models import OptionInquiryRawParams
from app.subgraphs.ticker.resolver import TickerResolution


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
    monkeypatch.setattr(inquiry, "resolve_ticker_full", AsyncMock(return_value=TickerResolution(
        resolved=[TickerCandidate(windCode="600000.SH", insShtDesc="甲证券", from_goats=True)],
        hitl_pending=[],
    )))
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
