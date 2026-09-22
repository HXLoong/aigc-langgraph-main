"""回执、待核对与错误兜底分支均须保留可区分的 trace decision。"""
from __future__ import annotations

import pytest

from app.graph.state import ErrorInfo, TickerCandidate
from app.nodes.render import render


def _decision(update: dict) -> str | None:
    entries = [e for e in update.get("trace", []) if getattr(e, "node", None) == "render"]
    assert len(entries) == 1, update.get("trace")
    return entries[0].decision


@pytest.mark.asyncio
async def test_passthrough_when_subgraph_already_replied() -> None:
    out = await render({"reply_text": "已有回复"})
    assert "reply_text" not in out
    assert _decision(out) == "passthrough"


@pytest.mark.asyncio
async def test_api_result_branch() -> None:
    out = await render({"api_result": "后端卡片", "product_type": "swap"})
    assert out["reply_text"] == "后端卡片"
    assert _decision(out) == "api_result"


@pytest.mark.asyncio
async def test_local_candidates_without_receipt_use_uncertain_branch() -> None:
    out = await render({
        "product_type": "swap", "intent": "place_order_request",
        "ticker_hitl_candidates": [{"keyword": "茅台", "candidates": [{"windCode": "600519.SH"}]}],
    })
    assert _decision(out) == "backend_no_result"
    assert "600519.SH" not in out["reply_text"]


@pytest.mark.asyncio
async def test_empty_tickers_do_not_select_zero_match_branch() -> None:
    out = await render({
        "product_type": "option", "tickers": [], "expected_action": "place", "place_params": {"orderList": [{}]},
        "raw_text": "x", "intent": "place_order",
    })
    assert _decision(out) == "backend_no_result"


@pytest.mark.asyncio
async def test_error_branches_are_distinguished() -> None:
    unreachable = await render({
        "product_type": "swap",
        "error": ErrorInfo(node="n", type="BackendUnreachableError", message="down"),
    })
    cascade = await render({
        "product_type": "swap", "error": ErrorInfo(node="n", type="RuntimeError", message="x"),
    })
    assert _decision(unreachable) == "error:backend_unreachable"
    assert _decision(cascade) == "error:cascade_fail"


@pytest.mark.asyncio
async def test_known_intent_without_receipt_is_labelled() -> None:
    out = await render({"product_type": "option", "intent": "new_inquiry",
                        "tickers": [TickerCandidate(windCode="600519.SH", from_goats=True)]})
    assert _decision(out) == "backend_no_result"


@pytest.mark.asyncio
async def test_empty_state_fallback_is_labelled() -> None:
    assert _decision(await render({})) == "no_reply"
