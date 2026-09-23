"""Quoted/raw selection uses authoritative holdings before submitting close requests."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.subgraphs.close import place_close as pc_module
from app.subgraphs.close.place_close import close_place_close
from tests.subgraphs.close.candidate_fixtures import close_candidates


def _patch_llm(monkeypatch: pytest.MonkeyPatch, params: BaseModel) -> None:
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=params)
    monkeypatch.setattr(pc_module, "get_qwen_thinking", lambda: model)


def _patch_query_close_orders(monkeypatch: pytest.MonkeyPatch, holdings: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(pc_module, "_fetch_order_data", AsyncMock(return_value=holdings))


def _patch_operate(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    captured = MagicMock()

    async def operate(self, req):  # type: ignore[no-untyped-def]
        captured(req)
        return {"code": 0, "data": "mock-backend-result"}

    monkeypatch.setattr("app.subgraphs.close.backend.OptionClientHttpx.operate", operate)
    return captured


def _full_context(raw_text: str) -> dict[str, Any]:
    return {"raw_text": raw_text, "conversation_id": "t-seq", "user_id": "u-seq",
            "room_id": "r-seq", "message_id": 1}


def _sent(captured: MagicMock) -> list[dict[str, Any]]:
    return captured.call_args.args[0].close_order_req_vo.model_dump()["closeOrderList"]


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate_field", ["orderId", "internalTradeId"])
async def test_direct_contract_identity_is_resolved_by_code(monkeypatch, candidate_field):
    contract = "OPT-SZZSCF20260001"
    _patch_query_close_orders(monkeypatch, [{"orderId": None, "contractCode": contract}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({candidate_field: contract}))
    result = await close_place_close(_full_context(f"我想平掉 {contract}"))
    assert result.get("error") is None
    assert _sent(captured)[0]["orderId"] is None
    assert _sent(captured)[0]["internalTradeId"] == contract


@pytest.mark.asyncio
async def test_contract_and_sequence_can_select_the_same_record(monkeypatch):
    contract = "OPT-SZZSCF20260001"
    _patch_query_close_orders(monkeypatch, [{"orderId": None, "contractCode": contract}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "序号1", "internalTradeId": contract,
                                              "closeOrderNotionalDelta": "200万"}))
    result = await close_place_close(_full_context(f"序号1平200万，合约编号 {contract}"))
    assert result.get("error") is None
    assert _sent(captured)[0]["internalTradeId"] == contract
    assert _sent(captured)[0]["closeOrderNotionalDelta"] == "2000000"


@pytest.mark.asyncio
async def test_full_close_preserves_explicit_execution_values(monkeypatch):
    contract = "OPT-SZZSCF20260001"
    _patch_query_close_orders(monkeypatch, [{"orderId": None, "contractCode": contract}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"internalTradeId": contract, "closeOrderType": "POV",
                                              "closeOrderPovRatio": "25", "confirmFullClose": "全平"}))
    result = await close_place_close(_full_context(f"{contract} 全平 POV25"))
    assert result.get("error") is None
    assert _sent(captured)[0]["closeOrderType"] == "POV"
    assert _sent(captured)[0]["closeOrderPovRatio"] == 25
    assert _sent(captured)[0]["confirmFullClose"] is True


@pytest.mark.asyncio
async def test_sequence_resolves_real_identity_and_does_not_rewrite_backend_reply(monkeypatch):
    _patch_query_close_orders(monkeypatch, [{"orderId": "CO-20260506-85AB8526", "contractCode": "OPT-A"}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "序号1", "closeOrderNotionalDelta": "300万",
                                              "closeOrderType": "不用跟量"}))
    result = await close_place_close(_full_context("序号1平300万 不用跟量，正常挂单"))
    assert result.get("error") is None
    assert _sent(captured)[0]["orderId"] == "CO-20260506-85AB8526"
    assert _sent(captured)[0]["internalTradeId"] == "OPT-A"
    assert _sent(captured)[0]["closeOrderType"] == "市价单"
    assert result["api_result"] == "mock-backend-result"


@pytest.mark.asyncio
async def test_sequence_uses_contract_when_query_has_no_order_id(monkeypatch):
    _patch_query_close_orders(monkeypatch, [{"orderId": None, "contractCode": "OPT-A"}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "序号1", "closeOrderNotionalDelta": "200万"}))
    result = await close_place_close(_full_context("序号1平200万"))
    assert result.get("error") is None
    assert _sent(captured)[0]["orderId"] is None
    assert _sent(captured)[0]["internalTradeId"] == "OPT-A"


@pytest.mark.asyncio
async def test_sequence_uses_second_holding(monkeypatch):
    _patch_query_close_orders(monkeypatch, [
        {"orderId": "CO-20260506-AAAA0001", "contractCode": "OPT-A"},
        {"orderId": "CO-20260506-BBBB0002", "contractCode": "OPT-B"}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "序号2", "closeOrderNotionalDelta": "200万"}))
    result = await close_place_close(_full_context("序号2平200万"))
    assert result.get("error") is None
    assert _sent(captured)[0]["orderId"] == "CO-20260506-BBBB0002"


@pytest.mark.asyncio
async def test_real_order_id_is_not_overridden_by_query_position(monkeypatch):
    _patch_query_close_orders(monkeypatch, [
        {"orderId": "CO-20260506-AAAA0001", "contractCode": "OPT-A"},
        {"orderId": "CO-20260506-BBBB0002", "contractCode": "OPT-B"}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "CO-20260506-BBBB0002",
                                              "closeOrderNotionalDelta": "300万"}))
    result = await close_place_close(_full_context("平 CO-20260506-BBBB0002 300万"))
    assert result.get("error") is None
    assert _sent(captured)[0]["orderId"] == "CO-20260506-BBBB0002"


@pytest.mark.asyncio
async def test_unresolved_sequence_does_not_call_backend(monkeypatch):
    _patch_query_close_orders(monkeypatch, [])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates({"orderId": "序号1", "closeOrderNotionalDelta": "300万"}))
    result = await close_place_close(_full_context("序号1平300万"))
    assert result.get("error") is None
    assert result["reply_text"] == "未能识别平仓参数，请提供订单号或持仓序号。"
    captured.assert_not_called()


@pytest.mark.asyncio
async def test_multi_seq_legs_calculate_remainder_and_full_close_independently(monkeypatch):
    _patch_query_close_orders(monkeypatch, [
        {"orderId": "CO-20260506-AAAA0001", "contractCode": "OPT-A", "availableNotional": 6000000},
        {"orderId": "CO-20260506-BBBB0002", "contractCode": "OPT-B"}])
    captured = _patch_operate(monkeypatch)
    _patch_llm(monkeypatch, close_candidates(
        {"orderId": "序号1", "closeOrderNotionalDelta": "留300万", "closeOrderType": "最大跟量"},
        {"orderId": "序号2", "confirmFullClose": "全平"}))
    result = await close_place_close(_full_context("序号1留300万，序号2全平，全部最大跟量"))
    assert result.get("error") is None
    first, second = _sent(captured)
    assert first["orderId"] == "CO-20260506-AAAA0001"
    assert first["closeOrderNotionalDelta"] == "3000000"
    assert first["hasFastExecutionIntent"] is True
    assert first["closeOrderType"] is None and first["closeOrderPovRatio"] is None
    assert second["orderId"] == "CO-20260506-BBBB0002"
    assert second["confirmFullClose"] is True
    assert second["closeOrderType"] is None and second["closeOrderPovRatio"] is None
