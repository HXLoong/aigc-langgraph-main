"""明确候选选择仍由代码绑定范围，联合解析只提供待验证指针。"""
from __future__ import annotations

import pytest

from app.subgraphs.swap.selection_rules import counterparty_choice, ticker_choice, validate_picks

ORDER = "H-20260918-1234567890"


@pytest.mark.parametrize("raw", ["B", "选择 B", "交易对手：测试乙", "测试乙"])
def test_literal_counterparty_choice(raw):
    """字母与名称选择得到同一授权对手，不需要模型补查。"""
    state = {"raw_text": raw, "place_params": {"orderList": [{"orderId": ORDER}]},
        "swap_counterparties": [{"sort": "A", "shortName": "测试甲"}, {"sort": "B", "shortName": "测试乙"}]}
    choice = counterparty_choice(state)
    assert choice is not None
    picks = validate_picks(state, [p.model_dump() for p in choice.picks], "counterparty")
    assert picks[0]["idx"] == 0 and picks[0]["directName"] == "测试乙"


@pytest.mark.parametrize("raw", ["2", "选择2", "JD.O", "JD.COM"])
def test_literal_ticker_choice(raw):
    """候选序号和名称只能绑定当前订单的引用候选。"""
    state = {"raw_text": raw, "place_params": {"orderList": [{"orderId": ORDER}]},
        "quote_ticker_candidates": [{"orderId": ORDER, "candidates": [
            {"seq": 1, "code": "9618.HK", "name": "京东集团-SW"},
            {"seq": 2, "code": "JD.O", "name": "JD.COM"}]}]}
    choice = ticker_choice(state)
    assert choice is not None
    picks = validate_picks(state, [p.model_dump() for p in choice.picks], "ticker")
    assert picks[0]["seq"] == 2 and picks[0]["directRef"] == "JD.O"
