"""Identity-only nodes retain the source and scope that their Code parser used."""
from unittest.mock import AsyncMock, MagicMock

from app.extraction.fields import FieldRecord
from app.subgraphs.close import confirm_close as close
from app.subgraphs.option import extract_cancel as cancel
from app.subgraphs.option import extract_cancel_place as cancel_place
from app.subgraphs.option import extract_query as query
from app.subgraphs.swap import confirm as swap

Q1, Q2 = "Q-20260918-0000000001", "Q-20260918-0000000002"
H1, H2 = "H-20260918-0000000001", "H-20260918-0000000002"
C1, C2 = "CO-20260918-AAAAAAAA", "CO-20260918-BBBBBBBB"


async def test_option_cancel_place_uses_quote_even_when_raw_contains_another_id(monkeypatch):
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "原样回复"})
    monkeypatch.setattr(cancel_place, "call_option_backend", backend)
    result = await cancel_place.option_extract_cancel_place({"raw_text": f"取消{Q1}", "quote_content": Q2})
    assert result["cancel_params"]["orderList"] == [{"orderId": Q2}]
    assert result["field_records"]["option/cancel_place.orderList.0.orderId"].origin == "quote"
    assert backend.call_args.args[0]["field_records"]["option/cancel_place.orderList.0.orderId"].locked


async def test_swap_confirm_selected_quote_scope_is_recorded_and_memory_cannot_replace_quote(monkeypatch):
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "原样回复"})
    monkeypatch.setattr(swap, "call_swap_backend", backend)
    result = await swap.swap_confirm({"raw_text": "序号2，确认下单", "quote_content": f"序号1：{H1}\n序号2：{H2}", "intent": "confirm_order"})
    assert result["confirm"]["orderList"] == [{"orderId": H2}]
    assert result["field_records"]["swap/confirm.orderList.0.orderId"].origin == "quote"
    assert result["field_records"]["swap/confirm.orderList.0.orderId.selection"].origin == "raw"
    backend.reset_mock()
    rejected = await swap.swap_confirm({"raw_text": "确认下单", "intent": "confirm_order",
        "last_confirmed_params": {"product_type": "swap", "order_ids": [H1]}})
    assert rejected["confirm"] is None
    backend.assert_not_called()


async def test_close_selected_ids_use_actual_request_array_paths(monkeypatch):
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "原样回复"})
    monkeypatch.setattr(close, "call_close_backend", backend)
    result = await close.close_confirm_close({"raw_text": "确认平仓第二笔", "quote_content": f"{C1}\n{C2}"})
    assert result["confirm"]["confirmOrderNoList"] == [C2]
    record = result["field_records"]["close/confirm.confirmOrderNoList.0"]
    assert record.origin == "quote" and record.locked
    assert backend.call_args.kwargs["close_order_req_vo"]["confirmOrderNoList"] == [C2]
    from app.extraction.identity import protect_identity_lists
    protected, rejected = protect_identity_lists(
        {"field_records": result["field_records"]}, {"confirmOrderNoList": [C1]},
    )
    assert protected["confirmOrderNoList"] == [C2]
    assert rejected["close/confirm.confirmOrderNoList.0"].value == C1


async def test_query_without_id_does_not_invent_provenance_for_java_defaults(monkeypatch):
    monkeypatch.setattr(query, "call_option_backend", AsyncMock(return_value={"api_code": 0, "api_result": "近期订单"}))
    result = await query.option_extract_query({"raw_text": "查订单"})
    assert result["query_filter"]["orderList"] == [{"orderId": None}]
    assert result.get("field_records", {}) == {}


async def test_locked_option_identity_protects_wire_and_returned_scope(monkeypatch):
    client = MagicMock()
    client.operate = AsyncMock(return_value={"code": 0, "data": "原样回复"})
    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: client)
    result = await cancel.option_extract_cancel({"raw_text": f"撤单{Q2}", "conversation_id": "c", "room_id": "r", "user_id": "u", "message_id": 1,
        "field_records": {"option/cancel.orderList.0.orderId": FieldRecord(value=Q1, source="user", evidence=Q1, locked=True)}})
    assert client.operate.call_args.args[0].model_dump()["orderList"][0]["orderId"] == Q1
    assert result["cancel_params"]["orderList"][0]["orderId"] == Q1
