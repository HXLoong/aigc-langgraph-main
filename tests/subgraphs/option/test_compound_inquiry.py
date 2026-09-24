"""Compound call shorthand must retain both strike and verified source evidence."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.state import AgentState
from app.subgraphs.option import backend
from app.subgraphs.option import extract_inquiry as inquiry
from app.tools.option_client import FinancialOrderOpenApiSaveReqVO


def candidate(value: str) -> dict[str, Any]:
    return {"value": value, "evidence": value, "confidence": 0.9, "origin": "raw"}


def item(token: str, strike: str | None = None, stock: str = "宁德时代",
         tenor: str = "1M") -> dict[str, Any]:
    return {"stockCode": candidate(stock), "optionType": candidate(token),
            "strikePercentage": candidate(strike) if strike is not None else None,
            "tenor": candidate(tenor)}


def setup(monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value={"orderList": items},
    )
    monkeypatch.setattr(inquiry, "get_qwen_thinking", lambda: model)
    calls: list[dict[str, Any]] = []

    async def operate(self: Any, req: FinancialOrderOpenApiSaveReqVO) -> dict[str, Any]:
        calls.append(req.model_dump())
        return {"code": 0, "data": "BACKEND_CARD"}

    monkeypatch.setattr(backend.OptionClientHttpx, "operate", operate)
    return calls


def state(raw: str) -> AgentState:
    return {"raw_text": raw, "message_content": raw, "user_id": "test-user",
            "room_id": "test-room", "conversation_id": "compound-test", "message_id": 123}


@pytest.mark.parametrize(("token", "strike"), [
    ("100call", 100), ("80CALL", 80), ("90 Call", 90),
    ("100%call", 100), ("97.5% CALL", 97.5), ("100看涨", 100),
])
async def test_compound_call_reaches_backend_with_derived_strike(
    monkeypatch: pytest.MonkeyPatch, token: str, strike: float,
) -> None:
    calls = setup(monkeypatch, [item(token)])
    result = await inquiry.option_extract_inquiry(state(f"宁德时代，{token}，1M"))
    assert not result.get("error"), result
    assert len(calls) == 1
    order = calls[0]["orderList"][0]
    assert order["stockCode"] == "宁德时代"
    assert order["optionType"] == "欧式看涨"
    assert order["strikePercentage"] == strike
    assert result["api_result"] == "BACKEND_CARD"
    prefix = "option/inquiry.orderList.0."
    fields = result["field_records"]
    for key, value in (("optionType", "欧式看涨"), ("strikePercentage", strike)):
        record = fields[prefix + key]
        assert record.value == value and record.evidence == token
        assert record.origin == "raw" and record.source == "user" and record.locked
        assert record.confidence == 0.9
    assert fields[prefix + "strikePercentage"].derived_from == [prefix + "optionType"]


@pytest.mark.parametrize("explicit", ["100", "100%", "平值"])
async def test_matching_explicit_strike_keeps_its_own_evidence(
    monkeypatch: pytest.MonkeyPatch, explicit: str,
) -> None:
    calls = setup(monkeypatch, [item("100call", explicit)])
    result = await inquiry.option_extract_inquiry(state(f"宁德时代，100call，{explicit}，1M"))
    assert not result.get("error"), result
    assert calls[0]["orderList"][0]["strikePercentage"] == 100
    record = result["field_records"]["option/inquiry.orderList.0.strikePercentage"]
    assert record.evidence == explicit and record.derived_from == []


@pytest.mark.parametrize("explicit", ["80", "100/80", "无法确定"])
async def test_conflicting_or_unparseable_explicit_strike_stops_submission(
    monkeypatch: pytest.MonkeyPatch, explicit: str,
) -> None:
    calls = setup(monkeypatch, [item("100call", explicit)])
    result = await inquiry.option_extract_inquiry(state(f"宁德时代，100call，{explicit}，1M"))
    assert result.get("error")
    assert "执行价冲突" in result["error"].message
    assert calls == []


@pytest.mark.parametrize(("token", "explicit", "strike"), [
    ("call", "100", 100), ("CALL", None, None), ("欧式看涨", "80%", 80),
])
async def test_separate_type_and_strike_keep_existing_semantics(
    monkeypatch: pytest.MonkeyPatch, token: str, explicit: str | None, strike: float | None,
) -> None:
    calls = setup(monkeypatch, [item(token, explicit)])
    result = await inquiry.option_extract_inquiry(
        state(f"宁德时代，{explicit or ''}{token}，1M"),
    )
    assert not result.get("error"), result
    assert calls[0]["orderList"][0]["optionType"] == "欧式看涨"
    assert calls[0]["orderList"][0].get("strikePercentage") == strike


@pytest.mark.parametrize("token", ["recall", "100callback", "100put", "100call额外文字"])
async def test_partial_or_unsupported_type_never_submits(
    monkeypatch: pytest.MonkeyPatch, token: str,
) -> None:
    calls = setup(monkeypatch, [item(token)])
    result = await inquiry.option_extract_inquiry(state(f"宁德时代，{token}，1M"))
    assert result.get("error")
    assert calls == []


async def test_invented_compound_evidence_never_submits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = setup(monkeypatch, [item("100call")])
    result = await inquiry.option_extract_inquiry(state("宁德时代，80call，1M"))
    assert result.get("error")
    assert calls == []


async def test_compound_without_verified_record_cannot_derive_strike() -> None:
    result = await inquiry.inquiry_normalize({"iq_raw_params": {
        "orderList": [{"optionType": "100call", "tenor": "1M"}],
    }})
    assert result.get("error")
    assert "原文证据" in result["error"].message


async def test_expanded_orders_keep_their_own_derived_strike(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = setup(monkeypatch, [
        item("80call", stock="甲股票", tenor="1M/2M"),
        item("100call", stock="乙股票", tenor="3M"),
    ])
    result = await inquiry.option_extract_inquiry(state("甲股票80call 1M/2M；乙股票100call 3M"))
    assert not result.get("error"), result
    assert [o["strikePercentage"] for o in calls[0]["orderList"]] == [80, 80, 100]
    assert [o["tenor"] for o in calls[0]["orderList"]] == ["1M", "2M", "3M"]
    for index, token in enumerate(("80call", "80call", "100call")):
        prefix = f"option/inquiry.orderList.{index}."
        record = result["field_records"][prefix + "strikePercentage"]
        assert record.evidence == token and record.derived_from == [prefix + "optionType"]
