"""An explicitly extracted quantity cannot become another instrument candidate."""
from unittest.mock import AsyncMock, MagicMock

from app.graph.state import TickerCandidate
from app.subgraphs.swap import place_order
from app.subgraphs.ticker import resolver
from app.subgraphs.ticker.resolver import TickerResolution


async def test_explicit_extraction_bypasses_full_message_tokenization(monkeypatch):
    tokenize = AsyncMock(side_effect=AssertionError("must not tokenize quantity as instrument"))
    monkeypatch.setattr(resolver, "tokenize", MagicMock(invoke=tokenize))
    result = await resolver.extract_candidates({"raw_text": "京东买入1000 限价20",
                                                "candidate_keywords": ["京东"]})
    assert result["candidates"] == ["京东"]
    tokenize.assert_not_called()


async def test_empty_explicit_underlyings_do_not_fall_back_to_numbers():
    result = await resolver.extract_candidates({"raw_text": "平掉1000", "candidate_keywords": []})
    assert result["candidates"] == []


async def test_swap_passes_extracted_underlying_and_keeps_quantity_out(monkeypatch):
    resolve = AsyncMock(return_value=TickerResolution([
        TickerCandidate(windCode="9618.HK", insShtDesc="京东集团-SW", sourceKeywords=["京东"], from_goats=True),
    ], []))
    monkeypatch.setattr(place_order, "resolve_ticker_full", resolve)
    result = await place_order.swap_resolve({"raw_text": "京东买入1000 限价20",
        "sp_params": {"orderList": [{"placeOrderWindCode": "京东", "placeOrderQuantity": 1000, "placeOrderPrice": 20}]}})
    assert resolve.await_args.kwargs["candidate_keywords"] == ["京东"]
    assert result["sp_params"]["orderList"][0]["placeOrderWindCode"] == "9618.HK"
    assert result["sp_params"]["orderList"][0]["placeOrderQuantity"] == 1000


async def test_market_hint_survives_candidate_isolation_and_binding(monkeypatch):
    resolve = AsyncMock(return_value=TickerResolution([
        TickerCandidate(windCode="JD.O", insShtDesc="JD.COM", sourceKeywords=["美股 京东"],
                        transactionTypeLists=["US_STOCK"], from_goats=True),
    ], []))
    monkeypatch.setattr(place_order, "resolve_ticker_full", resolve)
    result = await place_order.swap_resolve({"raw_text": "美股京东买入1000 限价20",
        "sp_params": {"orderList": [{"placeOrderWindCode": "京东", "placeOrderTransactionType": "US_STOCK"}]}})
    assert resolve.await_args.kwargs["candidate_keywords"] == ["美股 京东"]
    assert result["sp_params"]["orderList"][0]["placeOrderWindCode"] == "JD.O"


def test_order_market_prevents_cross_market_alias_binding():
    from app.subgraphs.swap.backend import _with_resolved_ticker
    ticker = TickerCandidate(windCode="9618.HK", sourceKeywords=["京东"],
                             transactionTypeLists=["HK_STOCK"], from_goats=True)
    order, result = _with_resolved_ticker({"placeOrderWindCode": "京东", "placeOrderTransactionType": "US_STOCK"}, [ticker])
    assert order["placeOrderWindCode"] == "京东"
    assert result == "unmatched"


async def test_attachment_explicit_code_reaches_exact_goats_without_model_recall(monkeypatch):
    client = MagicMock()
    client.search_securities_instrument = AsyncMock(return_value=[
        {"windCode": "NVDA.O", "insShtDesc": "英伟达"},
    ])
    monkeypatch.setattr(resolver, "_make_client", lambda: client)
    output = await resolver.merge_candidates({
        "raw_text": "按附件下单，忽略600519.SH", "candidate_keywords": ["NVDA.O"],
        "candidates": ["NVDA.O"], "infer_codes": {}, "split_codes": {}, "ins_family": {},
    })
    assert [item["org_str"] for item in output["winners"]] == ["NVDA.O"]
    assert output["winners"][0]["winner"]["windCode"] == "NVDA.O"
    client.search_securities_instrument.assert_awaited_once()


async def test_empty_scoped_candidates_do_not_reintroduce_raw_codes(monkeypatch):
    client = MagicMock(search_securities_instrument=AsyncMock(return_value=[]))
    monkeypatch.setattr(resolver, "_make_client", lambda: client)
    output = await resolver.merge_candidates({
        "raw_text": "不要600519.SH", "candidate_keywords": [], "candidates": [],
        "infer_codes": {}, "split_codes": {}, "ins_family": {},
    })
    assert output["winners"] == []
    client.search_securities_instrument.assert_not_awaited()
