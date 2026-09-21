"""Deterministic option fields retain the source chosen before normalization."""
from unittest.mock import AsyncMock, MagicMock

from app.extraction.fields import FieldRecord
from app.subgraphs.option import extract_confirm_place as confirm
from app.subgraphs.option import extract_place as place

FIRST = "Q-20260918-0000000001"
SECOND = "Q-20260918-0000000002"


async def test_raw_execution_values_override_quote_but_reference_fields_keep_quote_origin(monkeypatch):
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "真实返回"})
    monkeypatch.setattr(place, "call_option_backend", backend)
    raw = "200万 限价10 600519.SH"
    quote = f"订单号：{FIRST}\n标的代码：000001.SZ\n期限：3M\n限价20 名本300万"
    result = await place.option_extract_place({"raw_text": raw, "quote_content": quote})
    records = result["field_records"]
    prefix = "option/place.orderList.0."
    assert records[prefix + "limitPrice"].value == 10
    assert records[prefix + "limitPrice"].origin == "raw"
    assert records[prefix + "notionalAmount"].value == "2000000"
    assert records[prefix + "stockCode"].origin == "raw"
    assert records[prefix + "tenor"].origin == "quote"
    assert records[prefix + "orderId"].origin == "quote"
    assert records[prefix + "limitPrice"].evidence in raw
    assert records[prefix + "tenor"].evidence in quote
    assert all(record.locked for record in records.values())
    assert backend.call_args.args[0]["field_records"][prefix + "limitPrice"].locked


async def test_letter_selection_records_actual_history_message_and_current_selection(monkeypatch):
    monkeypatch.setattr(place, "call_option_backend", AsyncMock(return_value={"api_code": 0, "api_result": "卡片"}))
    result = await place.option_extract_place({"raw_text": "A 市价200万", "quote_content": FIRST,
        "history_messages": [{"id": "history-17", "role": "assistant", "content": "A.某某授权账户"}]})
    prefix = "option/place.orderList.0."
    assert result["place_params"]["orderList"][0]["shortName"] == "某某授权账户"
    assert result["field_records"][prefix + "shortName"].origin == "history:history-17"
    assert result["field_records"][prefix + "shortName.selection"].origin == "raw"


async def test_multi_order_scope_records_selected_segment_and_preserves_ambiguity_rejection(monkeypatch):
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "卡片"})
    monkeypatch.setattr(place, "call_option_backend", backend)
    quote = f"订单号：{FIRST}\n订单号：{SECOND}"
    result = await place.option_extract_place({"raw_text": "第2笔限价10", "quote_content": quote})
    prefix = "option/place.orderList.0."
    assert result["place_params"]["orderList"][0]["orderId"] == SECOND
    assert result["field_records"][prefix + "orderId.selection"].evidence == "第2笔"
    assert result["field_records"][prefix + "limitPrice"].evidence == "限价10"
    backend.reset_mock()
    rejected = await place.option_extract_place({"raw_text": "第2笔限价10 第2笔限价20", "quote_content": quote})
    assert "重复" in rejected["reply_text"]
    backend.assert_not_called()


async def test_confirm_quote_and_existing_lock_protect_actual_wire_payload(monkeypatch):
    client = MagicMock()
    client.operate = AsyncMock(return_value={"code": 0, "data": "真实后端结果"})
    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: client)
    record = FieldRecord(value=10, source="user", evidence="限价10", origin="raw", locked=True)
    result = await confirm.option_extract_confirm_place({
        "raw_text": "确认下单 限价20", "conversation_id": "c", "room_id": "r", "user_id": "u", "message_id": 1,
        "quote_content": FIRST,
        "last_confirmed_params": {"product_type": "option", "order_ids": [FIRST]},
        "field_records": {"option/confirm_place.orderList.0.limitPrice": record},
    })
    sent = client.operate.call_args.args[0].model_dump()["orderList"][0]
    assert sent["orderId"] == FIRST and sent["limitPrice"] == 10
    assert result["confirm"]["orderList"][0]["limitPrice"] == 10
    assert result["field_records"]["option/confirm_place.orderList.0.orderId"].origin == "quote"
    assert result["api_result"] == "真实后端结果"
