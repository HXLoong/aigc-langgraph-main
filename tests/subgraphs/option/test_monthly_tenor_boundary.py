"""HTTP 期限只发送正整数 M；审计原文及字段证据保留原始表达。"""
import json
import re
from unittest.mock import AsyncMock

import httpx
import pytest

from app.nodes import fast_query
from app.subgraphs.option import extract_inquiry as inquiry
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.extract_place import option_extract_place
from app.tools.option_client import FinancialOrderOpenApiSaveReqVO, OptionClientHttpx

ORDER = "Q-20260922-0000000001"
CONTEXT = {"conversation_id": "tenor-test", "message_id": 1,
           "room_id": "test-room", "user_id": "test-user"}


@pytest.fixture
def wire(monkeypatch):
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "原始回执"})

    client = OptionClientHttpx(base_url="http://java.test", token="test",
                              transport=httpx.MockTransport(handler), dry_run=False)
    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: client)
    monkeypatch.setattr(fast_query, "_make_option_client", lambda: client)
    return client, payloads


@pytest.mark.parametrize("raw,expected", [
    ("半年", "6M"), ("1Y", "12M"), ("1y", "12M"), ("1年", "12M"),
    ("一年", "12M"), ("2年", "24M"), ("0.5Y", "6M"),
    ("三个月", "3M"), ("3个月", "3M"), ("3m", "3M"), ("6M", "6M"),
    ("3 个月", "3M"), ("1 年", "12M"),
])
async def test_current_tenor_overrides_quote_and_reaches_http_in_months(wire, raw, expected):
    _, sent = wire
    text = f"把期限改为{raw}，100万市价"
    result = await option_extract_place({**CONTEXT, "raw_text": text,
                                        "quote_content": f"{ORDER}\n期限：1M"})
    assert sent[0]["orderList"][0]["tenor"] == expected
    assert sent[0]["rawContent"] == text
    record = result["field_records"]["option/place.orderList.0.tenor"]
    assert record.value == expected and raw in record.evidence and record.origin == "raw"


@pytest.mark.parametrize("node", [option_extract_place, option_extract_confirm_place])
async def test_quoted_year_is_converted_even_without_current_tenor(wire, node):
    _, sent = wire
    raw = "确认下单" if node is option_extract_confirm_place else "市价100万"
    await node({**CONTEXT, "raw_text": raw, "quote_content": f"{ORDER}\n期限：1Y"})
    assert sent[0]["orderList"][0]["tenor"] == "12M"
    assert sent[0]["quoteContent"].endswith("1Y")


@pytest.mark.parametrize("raw", ["0M", "-1M", "1.5M", "abc", "3M或6M"])
async def test_invalid_explicit_change_never_restores_old_tenor(wire, raw):
    _, sent = wire
    result = await option_extract_place({**CONTEXT, "raw_text": f"期限改为{raw}，市价100万",
                                        "quote_content": f"{ORDER}\n期限：1M"})
    assert not sent
    assert "期限" in result.get("reply_text", "")


@pytest.mark.parametrize("path", ["entry", "subgraph"])
async def test_both_fast_inquiry_paths_normalize_all_tenors(wire, monkeypatch, path):
    _, sent = wire
    data = {"tenor": ["半年", "1Y", "1年", "3m"], "chatInstrument": "原始1Y询价"}
    if path == "entry":
        agent = AsyncMock()
        agent.parse_rfq_instrument.return_value = {"code": 0, "api_data_result_obj": data}
        monkeypatch.setattr(fast_query, "_make_agent_client", lambda: agent)
        await fast_query.quick_inquiry({**CONTEXT, "raw_text": "1Y询价"})
    else:
        await inquiry.inquiry_fast_submit({**CONTEXT, "raw_text": "1Y询价", "iq_rfq_data": data})
    assert sent[0]["optionRfq"]["tenor"] == ["6M", "12M", "12M", "3M"]
    assert data["tenor"] == ["半年", "1Y", "1年", "3m"]


@pytest.mark.parametrize("rfq", [False, True])
async def test_client_boundary_handles_tenors_and_preserves_raw(wire, rfq):
    client, sent = wire
    fields = {"optionRfq": {"tenor": ["1Y"]}} if rfq else {"orderList": [{"tenor": "1Y"}]}
    req = FinancialOrderOpenApiSaveReqVO(type="new_inquiry", conversationId="c", messageId=1,
        messageContent="1Y", rawContent="1Y", userId="u", roomId="r", **fields)
    await client.operate(req)
    value = sent[0]["optionRfq"]["tenor"][0] if rfq else sent[0]["orderList"][0]["tenor"]
    assert value == "12M" and re.fullmatch(r"[1-9]\d*M", value)
    assert sent[0]["rawContent"] == "1Y"


@pytest.mark.parametrize("rfq", [False, True])
async def test_invalid_boundary_tenor_prevents_entire_http_request(wire, rfq):
    client, sent = wire
    fields = {"optionRfq": {"tenor": ["1Y", "abc"]}} if rfq else {
        "orderList": [{"tenor": "1Y"}, {"tenor": "abc"}]}
    with pytest.raises(ValueError, match="期限"):
        req = FinancialOrderOpenApiSaveReqVO(type="new_inquiry", conversationId="c", messageId=1,
            messageContent="raw", rawContent="raw", userId="u", roomId="r", **fields)
        await client.operate(req)
    assert not sent


async def test_fast_inquiry_requires_current_message_identity(wire, monkeypatch):
    _, sent = wire
    agent = AsyncMock()
    agent.parse_rfq_instrument.return_value = {"code": 0, "api_data_result_obj": {"tenor": ["1M"]}}
    monkeypatch.setattr(fast_query, "_make_agent_client", lambda: agent)
    result = await fast_query.quick_inquiry({**CONTEXT, "message_id": None, "raw_text": "询价"})
    assert not sent and result.get("error") is not None


async def test_current_annual_tenor_can_replace_invalid_legacy_quote(wire):
    _, sent = wire
    await option_extract_place({**CONTEXT, "raw_text": "全部期限1Y，第一笔市价100万",
                                "quote_content": f"{ORDER}\n期限：1W"})
    assert sent[0]["orderList"][0]["tenor"] == "12M"


@pytest.mark.parametrize("tenor", ["1.5M", "1M/invalid"])
async def test_ordinary_inquiry_stops_before_submit_on_invalid_tenor(wire, monkeypatch, tenor):
    from unittest.mock import MagicMock

    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=
        inquiry.CANDIDATE_MODEL.model_validate({"orderList": [{"tenor": {
            "value": tenor, "evidence": tenor, "origin": "raw", "confidence": 1.0,
        }}]}))
    monkeypatch.setattr(inquiry, "get_qwen_thinking", lambda: model)
    _, sent = wire
    result = await inquiry.option_extract_inquiry({**CONTEXT, "raw_text": f"期权询价{tenor}"})
    assert not sent and "期限" in result.get("reply_text", "")


@pytest.mark.parametrize("path", ["entry", "subgraph"])
async def test_fast_inquiry_invalid_array_is_a_correction_not_a_write(wire, monkeypatch, path):
    _, sent = wire
    data = {"tenor": ["1Y", "abc"]}
    if path == "entry":
        agent = AsyncMock()
        agent.parse_rfq_instrument.return_value = {"code": 0, "api_data_result_obj": data}
        monkeypatch.setattr(fast_query, "_make_agent_client", lambda: agent)
        result = await fast_query.quick_inquiry({**CONTEXT, "raw_text": "询价"})
    else:
        result = await inquiry.inquiry_fast_submit({**CONTEXT, "iq_rfq_data": data})
    assert not sent and "期限" in result.get("reply_text", "")


async def test_confirmation_keeps_contiguous_raw_evidence(wire):
    raw = "1Y 确认下单 限价10"
    result = await option_extract_confirm_place({**CONTEXT, "raw_text": raw, "quote_content": ORDER})
    _, sent = wire
    assert sent[0]["orderList"][0]["tenor"] == "12M"
    for record in result["field_records"].values():
        if record.origin == "raw" and record.evidence:
            assert record.evidence in raw
