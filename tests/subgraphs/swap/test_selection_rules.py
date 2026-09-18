"""Explicit choices in one known order are deterministic, not another model call."""
from unittest.mock import MagicMock

import pytest

from app.subgraphs.swap import select_counterparty, select_ticker

ORDER = "H-20260918-1234567890"


@pytest.mark.parametrize("raw", ["B", "选择 B", "交易对手：测试乙", "测试乙"])
async def test_literal_counterparty_choice_skips_model(monkeypatch, raw):
    model = MagicMock(side_effect=AssertionError("literal choice must use code"))
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", model)
    result = await select_counterparty.swap_select_counterparty({
        "raw_text": raw, "place_params": {"orderList": [{"orderId": ORDER}]},
        "swap_counterparties": [{"sort": "A", "shortName": "测试甲"}, {"sort": "B", "shortName": "测试乙"}],
    })
    assert not result.get("error")
    pick = result["swap_counterparty_picks"]["picks"][0]
    assert pick["idx"] == 0 and pick["directName"] == "测试乙"
    model.assert_not_called()


@pytest.mark.parametrize("raw", ["2", "选择2", "JD.O", "JD.COM"])
async def test_literal_ticker_choice_skips_model(monkeypatch, raw):
    model = MagicMock(side_effect=AssertionError("literal choice must use code"))
    monkeypatch.setattr(select_ticker, "get_qwen_complex", model)
    result = await select_ticker.swap_select_ticker({
        "raw_text": raw, "place_params": {"orderList": [{"orderId": ORDER}]},
        "quote_ticker_candidates": [{"orderId": ORDER, "candidates": [
            {"seq": 1, "code": "9618.HK", "name": "京东集团-SW"},
            {"seq": 2, "code": "JD.O", "name": "JD.COM"},
        ]}],
    })
    assert not result.get("error")
    assert result["swap_ticker_picks"][0]["seq"] == 2
    model.assert_not_called()


async def test_empty_authorized_counterparties_never_asks_model_to_invent_one(monkeypatch):
    model = MagicMock(side_effect=AssertionError("no candidates"))
    monkeypatch.setattr(select_counterparty, "get_qwen_complex", model)
    result = await select_counterparty.swap_select_counterparty({"raw_text": "选A", "swap_counterparties": []})
    assert not result.get("error")
    assert result["swap_counterparty_picks"] == {"hasSignal": False, "picks": []}
