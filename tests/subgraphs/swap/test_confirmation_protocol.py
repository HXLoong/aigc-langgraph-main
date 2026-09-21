"""CWAIJY-957: confirm only the orders the user explicitly selected."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.subgraphs.swap import intent as intent_module
from app.subgraphs.swap.confirm import swap_confirm
from app.subgraphs.swap.graph import build_swap_graph
from app.subgraphs.swap.models import SwapIntentOutput
from app.tools.swap_client import SwapClientHttpx
from tests.intent_fixtures import intent_reply, mock_ainvoke

CASES = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "swap_confirmation_cases.json").read_text()
)


def capture_backend(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    async def operate(self, req):
        calls.append(req.model_dump(by_alias=True))
        return {"code": 0, "data": "OFFLINE_CONFIRMATION_RESULT"}

    monkeypatch.setattr(SwapClientHttpx, "operate", operate)
    # A classifier must not bypass the deterministic confirmation guard.
    structured = MagicMock(ainvoke=mock_ainvoke(intent_reply(SwapIntentOutput, type="confirm_order")))
    model = MagicMock()
    model.with_structured_output.return_value = structured
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: model)
    return calls


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
async def test_shared_confirmation_contract(monkeypatch, case) -> None:
    calls = capture_backend(monkeypatch)
    result = await build_swap_graph().ainvoke({
        "raw_text": case["raw"], "quote_content": case["quote"],
        "product_type": "swap", "swap_input_mode": "text",
        "conversation_id": "protocol-test", "message_id": 123,
        "user_id": "test-user", "room_id": "test-room",
    })
    if case["error"]:
        assert calls == [], "invalid confirmation must never call the trading API"
        if case["error"] != "format":
            assert result.get("reply_text"), "protocol errors require a deterministic correction"
    else:
        assert len(calls) == 1
        assert [item["orderId"] for item in calls[0]["orderList"]] == case["orderIds"]
        assert result["api_result"] == "OFFLINE_CONFIRMATION_RESULT"


@pytest.mark.parametrize("quote", ["", "没有合法订单号的引用"])
async def test_confirmation_never_expands_from_memory(monkeypatch, quote) -> None:
    calls = capture_backend(monkeypatch)
    result = await swap_confirm({
        "intent": "confirm_order", "raw_text": "确认下单", "quote_content": quote,
        "conversation_id": "protocol-test", "message_id": 123,
        "user_id": "test-user", "room_id": "test-room",
        "last_confirmed_params": {"product_type": "swap", "order_ids": ["H-20260918-0000000001"]},
    })
    assert calls == []
    assert result.get("reply_text")


@pytest.mark.parametrize("raw", ["不要确认下单", "确定下单", "确认下单 H-20260918-0000000001"])
async def test_direct_confirmation_node_enforces_format(monkeypatch, raw) -> None:
    calls = capture_backend(monkeypatch)
    await swap_confirm({
        "intent": "confirm_order", "raw_text": raw,
        "quote_content": "H-20260918-0000000001",
        "conversation_id": "protocol-test", "message_id": 123,
        "user_id": "test-user", "room_id": "test-room",
    })
    assert calls == []
