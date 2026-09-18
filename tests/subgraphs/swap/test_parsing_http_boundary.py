"""固定 LLM/HTTP 外部响应，经过真实提取、GOATS 校验、DTO、提交与渲染。"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from evidence_support import candidate_output

from app.nodes.render import render
from app.subgraphs.swap import backend, place_order
from app.subgraphs.swap.fresh_counterparty import swap_recognize_fresh_counterparty
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from app.subgraphs.ticker import resolver, tools
from app.subgraphs.ticker.models import (
    InferCodeOutput,
    JudgeTypeOutput,
    RankOutput,
    SplitKeywordsOutput,
)
from app.tools.swap_client import SwapClientHttpx
from app.tools.ticker_client import TickerClientHttpx
from tests.subgraphs.swap.test_fresh_counterparty import patch_recognition
from tests.subgraphs.ticker.test_context_filter import REPORTS, SHORTNAME


@pytest.mark.parametrize("case", [0, 1], ids=["report-pov-3071", "report-average-price"])
@pytest.mark.parametrize("reply,code", [
    ("-----场外收益互换详情-----\n单号：H-20260911-1234567890\n委托数量：【待补充】\n", 0),
    ("无持仓，无法卖出。\n请核对持仓。", 400),
    ("订单处理中，请勿重复提交", 0),
])
async def test_swap_request_and_backend_reply_survive_real_http_chain(
    monkeypatch, case, reply, code,
) -> None:
    raw = REPORTS[case]
    params = SwapPlaceOrderParams(orderList=[
        SwapOrderItem(
            placeOrderWindCode=symbol, placeOrderQuantity=quantity,
            placeOrderOrderDirection="SELL", placeOrderQuantityUnit="SHARE",
            placeOrderPriceType="MarketOrder" if case == 0 else None,
            placeOrderPrice=None if case == 0 else price,
            placeOrderAlgorithmType="POV" if case == 0 else "TWAP",
            placeOrderPovPercent=7 if case == 0 else None,
            placeOrderShortname=None if index == 0 else SHORTNAME,
        )
        for index, (symbol, quantity, price) in enumerate([
            ("NVDA", 1453, 883.9758), ("TSM", 3071, 139.8888),
        ])
    ])
    original = params.model_dump()
    extract_llm = MagicMock()
    extract_llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=candidate_output(params, spellings={"SELL": "卖出", "SHARE": "股", "MarketOrder": "不限价", "POV": "pov", "TWAP": "均价", "1453": "1453" if case == 0 else "1,453", "3071": "3071" if case == 0 else "3,071"}))
    monkeypatch.setattr(place_order, "get_qwen_complex", lambda: extract_llm)
    patch_recognition(monkeypatch, {"hasSignal": True, "matches": [
        {"shortName": SHORTNAME, "evidence": SHORTNAME},
    ]})

    llm_candidates = []
    ticker_calls: list[type] = []
    async def ticker_reply(model, messages):
        _, user = (message.content for message in messages)
        candidates = json.loads(user.removeprefix("标的列表："))
        llm_candidates.extend(candidates)
        if model is JudgeTypeOutput:
            return JudgeTypeOutput.model_validate(
                {"results": {candidate: "EQUITY" for candidate in candidates}}
            )
        # 每个输入候选原样送查询，不在 stub 中替业务代码过滤噪音。
        data = {candidate: [candidate] for candidate in candidates}
        if model is SplitKeywordsOutput:
            return SplitKeywordsOutput.model_validate({"results": data})
        return InferCodeOutput.model_validate({"results": data})

    def make_structured(model):
        class _Structured:
            async def ainvoke(self, messages):
                ticker_calls.append(model)
                if model is RankOutput:
                    # 与迁移前行为一致：本 stub 中 rank 降级为空（旧路径解析失败 → []）
                    return RankOutput(ranked_codes=[])
                return await ticker_reply(model, messages)

        return _Structured()

    ticker_llm = MagicMock()
    ticker_llm.with_structured_output = MagicMock(side_effect=make_structured)
    monkeypatch.setattr(tools, "get_qwen_standard", lambda: ticker_llm)

    queries, requests = [], []
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if request.url.path == "/admin-api/integration/securities-instrument/select":
            assert request.method == "GET"
            keywords = [item["keyword"] for item in payload["keywordItems"]]
            queries.extend(keywords)
            instruments = [
                {"windCode": wind, "insShtDesc": name, "relevanceScore": 0}
                for symbol, wind, name in [
                    ("NVDA", "NVDA.O", "NVIDIA"), ("TSM", "TSM.N", "TAIWAN SEMICONDUCTOR"),
                ]
                if any(symbol in keyword for keyword in keywords)
            ]
            return httpx.Response(200, json={"code": 0, "data": instruments})
        assert request.url.path == "/admin-api/swap-order/operate"
        assert request.method == "POST"
        requests.append(payload)
        return httpx.Response(200, json={
            "code": code, "data": reply if code == 0 else None, "msg": reply,
        })

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(resolver, "_make_client", lambda: TickerClientHttpx(
        base_url="http://swap.test", token="test-only", transport=transport,
    ))
    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: SwapClientHttpx(
        base_url="http://swap.test", token="test-only", transport=transport, dry_run=False,
    ))
    state = {
        "raw_text": raw, "conversation_id": "parsing-regression", "message_id": "12345",
        "user_id": "test-user", "room_id": "test-room", "product_type": "swap",
        "swap_counterparties": [{"ctptyId": "1", "shortName": SHORTNAME}],
    }
    extracted = await place_order.swap_place_order(state)
    assert not extracted.get("error"), extracted.get("error")
    state.update(extracted)
    completed = await swap_recognize_fresh_counterparty(state)
    assert not completed.get("error"), completed.get("error")
    state.update(completed)
    submitted = await place_order.swap_place_order_submit(state)
    assert not submitted.get("error"), submitted.get("error")
    state.update(submitted)
    rendered = await render(state)

    assert len(requests) == 1
    payload = requests[0]
    assert payload["rawContent"] == payload["messageContent"] == raw
    assert payload["type"] == "place_order_request"
    orders = payload["orderList"]
    assert [order["placeOrderWindCode"] for order in orders] == ["NVDA.O", "TSM.N"]
    assert [order["placeOrderQuantity"] for order in orders] == [1453, 3071]
    assert [order.get("placeOrderPrice") for order in orders] == (
        [None, None] if case == 0 else ["883.9758", "139.8888"]
    )
    assert [order["placeOrderShortname"] for order in orders] == [SHORTNAME, SHORTNAME]
    assert [order["placeOrderAlgorithmType"] for order in orders] == [
        "POV" if case == 0 else "TWAP",
    ] * 2
    assert [order.get("placeOrderPovPercent") for order in orders] == (
        [7, 7] if case == 0 else [None, None]
    )
    assert submitted["api_code"] == code
    assert submitted["api_result"] == rendered["reply_text"] == reply
    assert state["raw_text"] == raw
    assert params.model_dump() == original
    assert all(ticker.from_goats for ticker in extracted["tickers"])
    assert len(ticker_calls) == 3
    extract_llm.with_structured_output.return_value.ainvoke.assert_awaited_once()
    assert queries and llm_candidates
    assert not any(char.isdigit() for candidate in llm_candidates + queries for char in candidate)
    assert not any("专用" in candidate for candidate in llm_candidates + queries)
