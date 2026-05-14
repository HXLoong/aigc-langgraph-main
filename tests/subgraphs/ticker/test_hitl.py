"""ticker HITL 消歧链路测试（Issue #30）。

验证：resolver 返回 hitl_pending 时，业务节点（swap.place_order /
option.extract_inquiry）正确将候选写入 state['ticker_hitl_candidates']。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.subgraphs.swap import place_order as place_order_mod
from app.subgraphs.swap.intent import swap_intent
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from app.subgraphs.ticker.resolver import TickerResolution


def _fake_resolution(hitl: bool) -> TickerResolution:
    """构造 HITL / 非 HITL 的 TickerResolution。"""
    if hitl:
        return TickerResolution(
            resolved=[],
            hitl_pending=[
                {
                    "keyword": "长江",
                    "candidates": [
                        {"windCode": "600900.SH", "insShtDesc": "长江电力", "relevanceScore": 85},
                        {"windCode": "000783.SZ", "insShtDesc": "长江证券", "relevanceScore": 80},
                    ],
                }
            ],
        )
    from app.graph.state import TickerCandidate
    return TickerResolution(
        resolved=[TickerCandidate(windCode="600900.SH", insShtDesc="长江电力", from_goats=True)],
        hitl_pending=[],
    )


def _patch_place_order_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 swap.place_order LLM 返回一个空下单参数（测试标的逻辑不关心 LLM 输出）。"""
    fake_params = SwapPlaceOrderParams(orderList=[SwapOrderItem(placeOrderWindCode="长江")])
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(return_value=fake_params))
    )
    monkeypatch.setattr(place_order_mod, "get_qwen_complex", lambda: fake_llm)


@pytest.mark.asyncio
async def test_hitl_triggered_writes_ticker_hitl_candidates_to_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolver 返回 hitl_pending → place_order 把候选写入 state['ticker_hitl_candidates']。"""
    _patch_place_order_llm(monkeypatch)
    monkeypatch.setattr(
        place_order_mod, "resolve_ticker_full", AsyncMock(return_value=_fake_resolution(hitl=True))
    )

    result = await place_order_mod.swap_place_order({"raw_text": "买长江"})

    assert "ticker_hitl_candidates" in result
    candidates = result["ticker_hitl_candidates"]
    assert len(candidates) == 1
    assert candidates[0]["keyword"] == "长江"
    assert len(candidates[0]["candidates"]) == 2
    assert result.get("tickers") == []


@pytest.mark.asyncio
async def test_no_hitl_does_not_write_ticker_hitl_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """resolver 自动选中 → state 无 ticker_hitl_candidates 字段。"""
    _patch_place_order_llm(monkeypatch)
    monkeypatch.setattr(
        place_order_mod, "resolve_ticker_full", AsyncMock(return_value=_fake_resolution(hitl=False))
    )

    result = await place_order_mod.swap_place_order({"raw_text": "买长江电力"})

    assert "ticker_hitl_candidates" not in result
    assert len(result.get("tickers", [])) == 1
    assert result["tickers"][0].windCode == "600900.SH"


@pytest.mark.asyncio
async def test_hitl_trace_records_hitl_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HITL 触发时 trace 记录 hitl_count > 0。"""
    _patch_place_order_llm(monkeypatch)
    monkeypatch.setattr(
        place_order_mod, "resolve_ticker_full", AsyncMock(return_value=_fake_resolution(hitl=True))
    )

    result = await place_order_mod.swap_place_order({"raw_text": "买长江"})

    place_order_trace = next(
        (e for e in result.get("trace", []) if e.node == "swap_place_order"), None
    )
    assert place_order_trace is not None
    assert place_order_trace.llm_output is not None
    assert place_order_trace.llm_output.get("hitl_count", 0) == 1
    assert "hitl=1" in place_order_trace.decision
