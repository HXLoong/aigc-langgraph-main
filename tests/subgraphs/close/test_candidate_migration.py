"""Evidence extraction and authoritative close identity/filter normalization."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.extraction.candidates import candidate_model
from app.extraction.fields import FieldRecord
from app.subgraphs.close import holding_query as hq
from app.subgraphs.close import place_close as pc
from app.subgraphs.close.backend import call_close_backend
from app.subgraphs.close.models import ClosePlaceParams, HoldingQueryParams
from app.tools.exceptions import BackendUnreachableError


def evidence(value: str, *, origin: str = "raw", context: str | None = None) -> dict:
    return {"value": value, "evidence": context or value, "origin": origin, "confidence": 0.99}


def mock_close(monkeypatch, rows, holdings=()):
    client = MagicMock()
    client.query_close_orders = AsyncMock(return_value={"code": 0, "data": list(holdings)})
    monkeypatch.setattr(pc, "OptionClientHttpx", lambda: client)
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value=candidate_model(ClosePlaceParams).model_validate({"closeOrderList": rows})
    )
    monkeypatch.setattr(pc, "get_qwen_thinking", lambda: model)
    submit = AsyncMock(return_value={"api_code": 0, "api_result": "真实后端结果"})
    monkeypatch.setattr(pc, "call_close_backend", submit)
    return client, model, submit


@pytest.mark.asyncio
async def test_lookup_network_failure_is_not_empty_holdings(monkeypatch):
    client = MagicMock()
    client.query_close_orders = AsyncMock(side_effect=BackendUnreachableError("option", "timeout"))
    monkeypatch.setattr(pc, "OptionClientHttpx", lambda: client)
    with pytest.raises(BackendUnreachableError):
        await pc._fetch_order_data([], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"code": 403, "msg": "无权限", "data": []}, {"code": 0, "data": {}}])
async def test_lookup_business_or_contract_failure_stops_before_llm_and_write(monkeypatch, response):
    client, model, submit = mock_close(monkeypatch, [])
    client.query_close_orders.return_value = response
    result = await pc.close_place_close({"raw_text": "序号1平200万"})
    assert result.get("error") is not None
    assert result["error"].node == "place_close_fetch_orders"
    model.with_structured_output.assert_not_called()
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_code_resolves_exact_quote_sequence_and_calculates_amount(monkeypatch):
    quote = "序号：8\n单号：CO-20260918-AAAAAAAA\n序号：18\n单号：CO-20260918-BBBBBBBB"
    mock_close(monkeypatch, [{"orderId": evidence("序号8"),
                            "closeOrderNotionalDelta": evidence("平一半"),
                            "closeOrderType": evidence("市价")}], [
        {"orderId": "CO-20260918-BBBBBBBB", "availableNotional": 9000000},
        {"orderId": "CO-20260918-AAAAAAAA", "contractCode": "OPT-A", "availableNotional": 5000000},
    ])
    result = await pc.close_place_close({"raw_text": "序号8平一半 市价", "quote_content": quote})
    assert result.get("error") is None
    row = result["close_params"]["closeOrderList"][0]
    assert row["orderId"] == "CO-20260918-AAAAAAAA"
    assert row["closeOrderNotionalDelta"] == "2500000"
    assert row["closeOrderType"] == "市价单"
    record = result["field_records"]["close/place_close.orderList.0.closeOrderNotionalDelta"]
    assert record.value == "2500000" and record.locked
    assert result["api_result"] == "真实后端结果"


@pytest.mark.asyncio
async def test_direct_contract_yuan_and_pov_are_normalized_by_code(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [{"internalTradeId": evidence("OPT-A"),
        "closeOrderNotionalDelta": evidence("200万"), "closeOrderType": evidence("跟量"),
        "closeOrderPovRatio": evidence("15%")}])
    result = await pc.close_place_close({"raw_text": "OPT-A平200万 跟量15%"})
    assert result.get("error") is None
    row = submit.call_args.kwargs["close_order_req_vo"]["closeOrderList"][0]
    assert row["orderId"] is None and row["internalTradeId"] == "OPT-A"
    assert row["closeOrderNotionalDelta"] == "2000000"
    assert row["closeOrderPovRatio"] == 15 and row["closeOrderType"] == "POV"


@pytest.mark.parametrize("selector,field", [
    ("OPT-A", "internalTradeId"), ("CO-20260924-AAAAAAAA", "orderId"),
])
async def test_quoted_order_identity_selects_its_own_balance_not_same_contract_rows(
    monkeypatch, selector, field,
):
    quote = "序号：8\n单号：CO-20260924-AAAAAAAA\n合约编号：OPT-A"
    _, _, submit = mock_close(monkeypatch, [{
        field: evidence(selector), "closeOrderNotionalDelta": evidence("平一半"),
        "closeOrderType": evidence("市价"),
    }], [
        {"orderId": None, "contractCode": "OPT-A", "availableNotional": 10000000},
        {"orderId": "CO-20260924-BBBBBBBB", "contractCode": "OPT-A", "availableNotional": 9000000},
        {"orderId": "CO-20260924-AAAAAAAA", "contractCode": "OPT-A", "availableNotional": 4000000},
    ])
    result = await pc.close_place_close({
        "raw_text": selector + "平一半 市价", "quote_content": quote,
    })
    assert result.get("error") is None
    row = submit.call_args.kwargs["close_order_req_vo"]["closeOrderList"][0]
    assert row["orderId"] == "CO-20260924-AAAAAAAA"
    assert row["internalTradeId"] == "OPT-A"
    assert row["closeOrderNotionalDelta"] == "2000000"


async def test_quoted_order_contract_conflicting_with_query_is_rejected(monkeypatch):
    quote = "序号：8\n单号：CO-20260924-AAAAAAAA\n合约编号：OPT-A"
    _, _, submit = mock_close(monkeypatch, [{
        "orderId": evidence("序号8"), "closeOrderNotionalDelta": evidence("平一半"),
    }], [{"orderId": "CO-20260924-AAAAAAAA", "contractCode": "OPT-B", "availableNotional": 4000000}])
    result = await pc.close_place_close({"raw_text": "序号8平一半", "quote_content": quote})
    assert result.get("error") is not None
    submit.assert_not_called()


async def test_contract_with_multiple_quoted_orders_remains_ambiguous(monkeypatch):
    quote = ("序号：1\n单号：CO-20260924-AAAAAAAA\n合约编号：OPT-A\n"
             "序号：2\n单号：CO-20260924-BBBBBBBB\n合约编号：OPT-A")
    _, _, submit = mock_close(monkeypatch, [{"internalTradeId": evidence("OPT-A")}], [
        {"orderId": "CO-20260924-AAAAAAAA", "contractCode": "OPT-A"},
        {"orderId": "CO-20260924-BBBBBBBB", "contractCode": "OPT-A"},
        {"orderId": None, "contractCode": "OPT-A"},
    ])
    result = await pc.close_place_close({"raw_text": "平掉 OPT-A", "quote_content": quote})
    assert result.get("error") is not None
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_unbound_errors_do_not_spread_supplement(monkeypatch):
    mock_close(monkeypatch, [{"closeOrderNotionalDelta": evidence("200万")}])
    quote = "期权平仓订单[CO-20260918-AAAAAAAA]参数需要完善\n期权平仓订单[CO-20260918-BBBBBBBB]参数需要完善"
    result = await pc.close_place_close({"raw_text": "200万", "quote_content": quote})
    assert result.get("error") is None
    rows = result["close_params"]["closeOrderList"]
    assert len(rows) == 2
    assert all(row["closeOrderNotionalDelta"] is None for row in rows)


@pytest.mark.asyncio
async def test_holding_filters_resolve_counterparty_from_authorized_data(monkeypatch):
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=
        candidate_model(HoldingQueryParams).model_validate({
            "closeable_only": evidence("平掉"), "keyCtptyIdList": [evidence("阿凡提")],
            "contractTypeList": [evidence("雪球")], "insFamilyList": [evidence("股票")],
        }))
    monkeypatch.setattr(hq, "get_qwen_thinking", lambda: model)
    submit = AsyncMock(return_value={"api_code": 0, "api_result": "实际持仓"})
    monkeypatch.setattr(hq, "call_close_backend", submit)
    result = await hq.close_holding_query({"raw_text": "平掉对手阿凡提的股票雪球",
        "option_counterparties": [{"ctptyId": 10049, "shortName": "临沂阿凡提"}]})
    assert result.get("error") is None
    query = submit.call_args.kwargs["close_order_req_vo"]["contractQuery"]
    assert query["keyCtptyIdList"] == [10049]
    assert query["insFamilyList"] == ["EQUITY"]
    assert query["contractTypeList"] == ["AUTOCALL"]
    assert query["allowCloseOut"] is True
    assert result["field_records"]["close/holding_query.keyCtptyIdList.0"].locked


@pytest.mark.asyncio
async def test_locked_close_amount_is_used_at_backend_boundary(monkeypatch):
    client = MagicMock()
    client.operate = AsyncMock(return_value={"code": 0, "data": "原样返回"})
    monkeypatch.setattr("app.subgraphs.close.backend.OptionClientHttpx", lambda: client)
    result = await call_close_backend({"conversation_id": "t", "room_id": "r", "user_id": "u",
        "message_id": 1, "field_records": {"close/place_close.orderList.0.closeOrderNotionalDelta":
            FieldRecord(value="2000000", source="user", evidence="200万", locked=True)}},
        intent="close_order_request", close_order_req_vo={"closeOrderList": [
            {"internalTradeId": "OPT-A", "closeOrderNotionalDelta": "8000000"}]})
    sent = client.operate.call_args.args[0].model_dump()["closeOrderReqVO"]["closeOrderList"][0]
    assert sent["closeOrderNotionalDelta"] == "2000000"
    assert result["api_result"] == "原样返回"


@pytest.mark.asyncio
async def test_calculated_llm_value_cannot_bypass_original_evidence(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [{"internalTradeId": evidence("OPT-A"),
        "closeOrderNotionalDelta": evidence("2000000", context="200万")}])
    result = await pc.close_place_close({"raw_text": "OPT-A平200万"})
    assert result["error"].node == "place_close_extract"
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_another_orders_amount_cannot_be_borrowed(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [
        {"internalTradeId": evidence("OPT-A"), "closeOrderNotionalDelta": evidence("300万")},
        {"internalTradeId": evidence("OPT-B"), "closeOrderNotionalDelta": evidence("200万")},
    ])
    result = await pc.close_place_close({"raw_text": "OPT-A平200万，OPT-B平300万"})
    assert result.get("error") is not None
    submit.assert_not_called()


@pytest.mark.parametrize("amount,available,expected", [
    ("三分之一", 5000000, "1666666"), ("留200万", 5000000, "3000000"),
    ("平50%", None, None), ("平125%", 5000000, None), ("1kw", None, "10000000"),
])
def test_close_arithmetic_uses_only_matching_authoritative_balance(amount, available, expected):
    from app.subgraphs.close.normalization import normalize_place_candidates
    from app.subgraphs.close.reference_parser import parse_reference_message
    raw = f"OPT-A {amount}"
    params, _ = normalize_place_candidates(candidate_model(ClosePlaceParams).model_validate(
        {"closeOrderList": [{"internalTradeId": evidence("OPT-A"),
                              "closeOrderNotionalDelta": evidence(amount)}]}),
        {"raw": raw}, parse_reference_message(None, raw),
        [{"contractCode": "OPT-B", "availableNotional": 99000000},
         {"contractCode": "OPT-A", "availableNotional": available}])
    assert params.close_order_list[0].close_order_notional_delta == expected


@pytest.mark.asyncio
async def test_unbound_negation_must_not_become_full_close_confirmation(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [{"confirmFullClose": evidence("全部平仓", context="不要全部平仓")}])
    result = await pc.close_place_close({"raw_text": "不要全部平仓", "quote_content":
        "期权平仓订单CO-20260918-AAAAAAAA：只能全部平仓"})
    assert not any(row.get("confirmFullClose") for row in result.get("close_params", {}).get("closeOrderList", []))
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_empty_candidates_do_not_resubmit_ambiguous_error_orders(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [])
    await pc.close_place_close({"raw_text": "你好", "quote_content":
        "期权平仓订单[CO-20260918-AAAAAAAA]参数需要完善\n期权平仓订单[CO-20260918-BBBBBBBB]参数需要完善"})
    submit.assert_not_called()


def test_bound_full_close_word_and_node_output_action(monkeypatch):
    from app.subgraphs.close.normalization import normalize_place_candidates
    from app.subgraphs.close.reference_parser import parse_reference_message
    raw = "平 OPT-A 全部"
    params, _ = normalize_place_candidates(candidate_model(ClosePlaceParams).model_validate({
        "closeOrderList": [{"internalTradeId": evidence("OPT-A"), "confirmFullClose": evidence("全部")}]}),
        {"raw": raw}, parse_reference_message(None, raw), [])
    assert params.close_order_list[0].confirm_full_close is True
    assert "expected_action" in pc.build_place_close_graph().output_channels


@pytest.mark.asyncio
async def test_bound_negation_cannot_be_removed_by_shorter_evidence(monkeypatch):
    _, _, submit = mock_close(monkeypatch, [{"internalTradeId": evidence("OPT-A"),
        "confirmFullClose": evidence("全部平仓")}])
    result = await pc.close_place_close({"raw_text": "OPT-A 不要全部平仓"})
    assert not any(row.get("confirmFullClose") for row in result.get("close_params", {}).get("closeOrderList", []))
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_standalone_full_close_clause_merges_only_authorized_confirmation_targets(monkeypatch):
    mock_close(monkeypatch, [{"orderId": evidence("CO-20260918-AAAAAAAA"),
                             "closeOrderNotionalDelta": evidence("200万")}])
    result = await pc.close_place_close({"raw_text": "CO-20260918-AAAAAAAA平200万，全部平仓",
        "quote_content": "期权平仓订单CO-20260918-BBBBBBBB：只能全部平仓"})
    rows = result["close_params"]["closeOrderList"]
    assert len(rows) == 2
    assert rows[0]["closeOrderNotionalDelta"] == "2000000"
    assert rows[1]["orderId"] == "CO-20260918-BBBBBBBB" and rows[1]["confirmFullClose"] is True
