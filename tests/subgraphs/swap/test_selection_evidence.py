"""Choices bind source evidence, explicit order scopes and authoritative candidates."""
from unittest.mock import AsyncMock, MagicMock

from app.graph.state import TickerCandidate
from app.subgraphs.swap import aggregate, apply_picks, select_counterparty, select_ticker

FIRST = "H-20260918-0000000001"
SECOND = "H-20260918-0000000002"


def state(raw):
    return {
        "raw_text": raw,
        "quote_content": f"序号：1 单号：{FIRST}\n序号：2 单号：{SECOND}",
        "place_params": {"orderList": [{"orderId": FIRST}, {"orderId": SECOND}]},
        "swap_counterparties": [{"sort": "A", "shortName": "甲账户"}, {"sort": "B", "shortName": "乙账户"}],
        "quote_ticker_candidates": [
            {"orderId": SECOND, "orderSeq": 2, "candidates": [{"seq": 1, "code": "MSFT.O", "name": "微软"}]},
            {"orderId": FIRST, "orderSeq": 1, "candidates": [{"seq": 1, "code": "AAPL.O", "name": "苹果"}]},
        ],
        "tickers": [TickerCandidate(windCode="AAPL.O", from_goats=True), TickerCandidate(windCode="MSFT.O", from_goats=True)],
    }


async def test_multi_order_counterparty_scopes_use_code_and_lock_final_names(monkeypatch):
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", MagicMock(side_effect=AssertionError("must use code")))
    data = state("序号2，B；序号1，A")
    data["quote_ticker_candidates"] = []
    data["quote_content"] = f"订单{FIRST}（序号1）：\n订单{SECOND}（序号2）："
    selected = await select_counterparty.swap_select_counterparty(data)
    assert not selected.get("error")
    out = await apply_picks.swap_apply_picks({**data, **selected})
    assert not out.get("error")
    assert [item["placeOrderShortname"] for item in out["place_params"]["orderList"]] == ["甲账户", "乙账户"]
    records = out["field_records"]
    assert records["swap/place_order.orderList.0.placeOrderShortname"].locked
    assert records["swap/place_order.orderList.1.placeOrderShortname.selection"].evidence == "序号2，B"


async def test_multi_order_ticker_scopes_do_not_use_candidate_block_position(monkeypatch):
    monkeypatch.setattr(select_ticker, "get_qwen_complex", MagicMock(side_effect=AssertionError("must use code")))
    data = state("第1笔选标的1；第2笔选标的1")
    selected = await select_ticker.swap_select_ticker(data)
    assert not selected.get("error")
    out = await apply_picks.swap_apply_picks({**data, **selected})
    assert not out.get("error")
    assert [item["placeOrderWindCode"] for item in out["place_params"]["orderList"]] == ["AAPL.O", "MSFT.O"]
    assert out["field_records"]["swap/place_order.orderList.1.placeOrderWindCode"].source == "goats"


async def test_multi_order_unscoped_choice_is_rejected(monkeypatch):
    output = {"hasSignal": True, "picks": [{"idx": 0, "letter": "B", "evidence": "B", "confidence": .9}]}
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=output)
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", lambda: model)
    result = await select_counterparty.swap_select_counterparty(state("B"))
    assert result.get("error")
    assert not result.get("swap_counterparty_picks")


async def test_llm_pointer_requires_real_selection_evidence(monkeypatch):
    output = {"hasSignal": True, "picks": [{"idx": 0, "letter": "B", "evidence": "选B", "confidence": .9}]}
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=output)
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", lambda: model)
    result = await select_counterparty.swap_select_counterparty(state("帮我决定吧"))
    assert result.get("error")


def test_unknown_ticker_and_conflicting_scope_never_fall_through():
    data = state("")
    assert aggregate.windcode_from_pick({"orderId": FIRST, "directRef": "FAKE.O"}, data["quote_ticker_candidates"]) is None
    assert aggregate.match_order_index({"orderId": SECOND}, [{"orderId": FIRST}], {}, True) == -1
    assert aggregate.match_order_index({"orderId": SECOND, "idx": 0}, data["place_params"]["orderList"], {}, False) == -1


async def test_forged_quote_code_needs_current_authority(monkeypatch):
    data = state("序号1选标的1")
    data["tickers"] = []
    client = MagicMock()
    client.search_securities_instrument = AsyncMock(return_value=[])
    monkeypatch.setattr(select_ticker, "_make_client", lambda: client, raising=False)
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value={"picks": [{
        "idx": 0, "orderId": FIRST, "seq": 1, "evidence": "序号1选标的1", "confidence": .9,
    }]})
    monkeypatch.setattr(select_ticker, "get_qwen_complex", lambda: model)
    result = await select_ticker.swap_select_ticker(data)
    assert result.get("error")
    assert not result.get("swap_ticker_picks")


async def test_fallback_can_locate_a_real_scoped_span_without_inventing_names(monkeypatch):
    data = state("把序号2，B这个选项应用一下")
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value={
        "hasSignal": True, "picks": [{"idx": 1, "orderId": SECOND, "letter": "B",
                                     "evidence": "序号2，B", "confidence": .8}],
    })
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", lambda: model)
    result = await select_counterparty.swap_select_counterparty(data)
    assert not result.get("error")
    assert result["swap_counterparty_picks"]["picks"][0]["directName"] == "乙账户"
    assert result["swap_counterparty_picks"]["picks"][0]["idx"] == 1
    model.with_structured_output.return_value.ainvoke.assert_awaited_once()


async def test_explicit_all_orders_is_scoped_and_conflicting_selectors_are_rejected(monkeypatch):
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", MagicMock(side_effect=AssertionError("must use code")))
    result = await select_counterparty.swap_select_counterparty(state("全部订单交易对手B"))
    assert not result.get("error")
    assert {pick["idx"] for pick in result["swap_counterparty_picks"]["picks"]} == {0, 1}
    conflict = await select_counterparty.swap_select_counterparty(state("序号1选A；序号1选B"))
    assert conflict.get("error")


async def test_explicit_all_ticker_choice_cannot_silently_skip_an_order(monkeypatch):
    data = state("全部订单选标的1")
    data["quote_ticker_candidates"] = data["quote_ticker_candidates"][:1]
    monkeypatch.setattr(select_ticker, "get_qwen_complex", MagicMock(side_effect=AssertionError("must use code")))
    out = await select_ticker.swap_select_ticker(data)
    assert out.get("error") is not None
    assert not out.get("swap_ticker_picks")
