"""互换订单的标的身份绑定：固定解析结果，验证真实节点和后端请求。"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.state import AgentState, TickerCandidate
from app.subgraphs.swap import backend as backend_module
from app.subgraphs.swap import place_order as po_module
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from app.subgraphs.ticker.resolver import TickerResolution
from app.tools.swap_client import SwapOrderOpenApiSaveReqVO


async def _extract_and_submit(
    monkeypatch: pytest.MonkeyPatch,
    params: SwapPlaceOrderParams,
    candidates: list[Any],
    raw_text: str = "互换下单",
) -> tuple[dict[str, Any], SwapOrderOpenApiSaveReqVO]:
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=params)
    monkeypatch.setattr(po_module, "get_qwen_complex", lambda: llm)
    monkeypatch.setattr(
        po_module, "resolve_ticker_full",
        AsyncMock(return_value=TickerResolution(candidates, [])),
    )
    backend_reply = "后端原始校验回复"
    client = MagicMock()
    client.operate = AsyncMock(return_value={"code": 0, "data": backend_reply})
    monkeypatch.setattr(backend_module, "SwapClientHttpx", lambda: client)
    state: AgentState = {
        "raw_text": raw_text, "conversation_id": "ticker-binding-replay",
        "message_id": "12345", "user_id": "test-user", "room_id": "test-room",
    }
    extracted = await po_module.swap_place_order(state)
    assert not extracted.get("error"), extracted.get("error")
    state.update(extracted)
    submitted = await po_module.swap_place_order_submit(state)
    assert not submitted.get("error"), submitted.get("error")
    assert submitted["api_result"] == backend_reply
    return extracted, client.operate.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("case_number", [1, 2])
async def test_prod_orders_keep_nvda_and_tsm_despite_spurious_candidates(
    monkeypatch: pytest.MonkeyPatch, case_number: int,
) -> None:
    """报告中的数量/价格噪音候选不得改变第二笔 TSM 的身份。"""
    if case_number == 1:
        raw_text = (
            "新增指令：标的：NVDA方向：卖出股份数量：1453股建仓方式：pov跟量7%，"
            "不限价备注：根据市场成交量成交，"
            "标的：TSM方向：卖出股份数量：3071股建仓方式：pov跟量7%"
        )
        codes = ["NVDA.O", "H01453.HK", "TSM.N", "3071.HK"]
        sources = [raw_text.split("，")[0], "1453", raw_text.split("，")[-1], "3071"]
        prices = [None, None]
    else:
        raw_text = "NVDA 卖出 1,453 股，均价 883.9758 TSM 卖出 3,071 股，均价 139.8888"
        codes = ["NVDA.O", "159758.SZ", "0883.HK", "TSM.N", "588880.SH", "0139.HK"]
        sources = ["NVDA", "9758", "883.", "TSM", "8888", "139."]
        prices = [883.9758, 139.8888]
    candidates = [
        TickerCandidate(windCode=code, sourceKeywords=[source], from_goats=True)
        for code, source in zip(codes, sources, strict=True)
    ]
    params = SwapPlaceOrderParams(orderList=[
        SwapOrderItem(
            placeOrderWindCode=code, placeOrderQuantity=quantity,
            placeOrderOrderDirection="SELL", placeOrderPrice=price,
            placeOrderPriceType="MarketOrder" if case_number == 1 else "LimitOrder",
            placeOrderAlgorithmType="POV" if case_number == 1 else "TWAP",
            placeOrderPovPercent=7 if case_number == 1 else None,
        )
        for code, quantity, price in zip(["NVDA", "TSM"], [1453, 3071], prices, strict=True)
    ])
    extracted, request = await _extract_and_submit(monkeypatch, params, candidates, raw_text)
    assert [o.place_order_wind_code for o in request.order_list] == ["NVDA.O", "TSM.N"]
    assert [o["placeOrderWindCode"] for o in extracted["place_params"]["orderList"]] == [
        "NVDA.O", "TSM.N",
    ]
    assert [o.place_order_quantity for o in request.order_list] == [1453, 3071]
    assert [o.place_order_price for o in request.order_list] == (
        [None, None] if case_number == 1 else [Decimal("883.9758"), Decimal("139.8888")]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("as_dicts", [False, True])
async def test_orders_bind_only_unique_identities_and_trace_the_outcome(
    monkeypatch: pytest.MonkeyPatch, as_dicts: bool,
) -> None:
    candidates = [
        TickerCandidate(
            windCode="600519.SH", insShtDesc="贵州茅台", insLngDesc="Kweichow Moutai",
            sourceKeywords=["茅台", "shared", "000858.SZ", "000858.BAD"], from_goats=True,
        ),
        TickerCandidate(
            windCode="00700.HK", insShtDesc="腾讯控股", sourceKeywords=["腾讯", "shared"],
            from_goats=True,
        ),
        TickerCandidate(windCode="TSM.N", sourceKeywords=["标的：TSM方向：卖出"], from_goats=True),
        TickerCandidate(windCode="TSM.N", sourceKeywords=["台积电"], from_goats=True),
        TickerCandidate(windCode="NVDA.O", from_goats=True),
        TickerCandidate(windCode="OTHER.N", sourceKeywords=["NVDA"], from_goats=True),
        TickerCandidate(windCode="DUAL.N", from_goats=True),
        TickerCandidate(windCode="DUAL.O", from_goats=True),
        TickerCandidate(windCode="FAKE.O", sourceKeywords=["unverified"], from_goats=False),
        TickerCandidate(windCode=" ", sourceKeywords=["empty-code"], from_goats=True),
    ]
    if as_dicts:
        candidates = [ticker.model_dump(by_alias=True) for ticker in reversed(candidates)]
    cases = [
        ("茅台", "600519.SH", "matched_alias"),
        ("茅台", "600519.SH", "matched_alias"),
        ("贵州茅台", "600519.SH", "matched_alias"),
        (" kweichow moutai ", "600519.SH", "matched_alias"),
        (" 600519 ", "600519.SH", "matched_alias"),
        (" 600519.sh ", "600519.SH", "matched_code"),
        ("腾讯", "00700.HK", "matched_alias"),
        ("腾讯控股", "00700.HK", "matched_alias"),
        ("tsm", "TSM.N", "matched_alias"),
        ("TSM", "TSM.N", "matched_alias"),
        ("台积电", "TSM.N", "matched_alias"),
        ("NVDA", "NVDA", "ambiguous"),
        ("NVDA.O", "NVDA.O", "matched_code"),
        ("DUAL", "DUAL", "ambiguous"),
        ("shared", "shared", "ambiguous"),
        ("unknown", "unknown", "unmatched"),
        ("000858.SZ", "000858.SZ", "unmatched"),
        ("000858.BAD", "000858.BAD", "unmatched"),
        ("茅", "茅", "unmatched"),
        ("700", "700", "unmatched"),
        ("unverified", "unverified", "unmatched"),
        ("FAKE", "FAKE", "unmatched"),
        ("FAKE.O", "FAKE.O", "unmatched"),
        ("empty-code", "empty-code", "unmatched"),
        (None, None, "missing"),
        ("", "", "missing"),
        ("  ", "  ", "missing"),
    ]
    params = SwapPlaceOrderParams(orderList=[
        SwapOrderItem(
            orderId=f"H-20260911-{index:010}", placeOrderWindCode=original,
            placeOrderQuantity=100 + index, placeOrderPrice=139.8888,
            placeOrderOrderDirection="SELL", placeOrderPriceType="LimitOrder",
            placeOrderAlgorithmType="POV", placeOrderPovPercent=7,
            placeOrderShortname="测试账户",
        )
        for index, (original, _, _) in enumerate(cases)
    ])
    originals = params.model_dump()
    extracted, request = await _extract_and_submit(monkeypatch, params, candidates)
    assert [o.place_order_wind_code for o in request.order_list] == [c[1] for c in cases]
    orders = extracted["place_params"]["orderList"]
    assert [o["placeOrderWindCode"] for o in orders] == [c[1] for c in cases]
    for original, bound in zip(originals["orderList"], orders, strict=True):
        assert {k: v for k, v in bound.items() if k != "placeOrderWindCode"} == {
            k: v for k, v in original.items() if k != "placeOrderWindCode"
        }
    assert [o.order_id for o in request.order_list] == [o.order_id for o in params.order_list]
    assert [o.place_order_quantity for o in request.order_list] == list(range(100, 127))
    assert all(o.place_order_price == Decimal("139.8888") for o in request.order_list)
    assert params.model_dump() == originals
    assert extracted["trace"][0].llm_output["ticker_bindings"] == [
        {
            "order_index": index, "original_wind_code": original,
            "resolved_wind_code": bound, "result": result,
        }
        for index, (original, bound, result) in enumerate(cases)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("original", [None, "unknown"])
@pytest.mark.parametrize("candidates", [
    [], [{"windCode": "TSM.N", "from_goats": True}],
])
async def test_no_single_candidate_fallback(
    monkeypatch: pytest.MonkeyPatch, original: str | None, candidates: list[dict[str, Any]],
) -> None:
    params = SwapPlaceOrderParams(orderList=[SwapOrderItem(placeOrderWindCode=original)])
    _, request = await _extract_and_submit(monkeypatch, params, candidates)
    assert request.order_list[0].place_order_wind_code == original


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", [
    {"windCode": "TSM.N"},
    {"windCode": "TSM.N", "from_goats": 1},
    {"windCode": "TSM.N", "from_goats": "true"},
    {"sourceKeywords": ["TSM"], "from_goats": True},
    {"windCode": None, "sourceKeywords": ["TSM"], "from_goats": True},
])
async def test_unverified_or_missing_codes_cannot_bind(
    monkeypatch: pytest.MonkeyPatch, candidate: dict[str, Any],
) -> None:
    params = SwapPlaceOrderParams(orderList=[SwapOrderItem(placeOrderWindCode="TSM")])
    _, request = await _extract_and_submit(monkeypatch, params, [candidate])
    assert request.order_list[0].place_order_wind_code == "TSM"
