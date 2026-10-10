"""联合模型的选择指针必须符合当前原文、授权列表与订单范围。"""
from __future__ import annotations

import pytest

from app.subgraphs.swap.apply_picks import swap_apply_picks
from app.subgraphs.swap.selection_rules import counterparty_choice, ticker_choice

FIRST = "H-20260918-0000000001"
SECOND = "H-20260918-0000000002"


def state(raw):
    """两笔订单的候选块故意反序，避免误按列表位置匹配。"""
    return {"raw_text": raw, "quote_content": f"序号：1 单号：{FIRST}\n序号：2 单号：{SECOND}",
        "place_params": {"orderList": [{"orderId": FIRST}, {"orderId": SECOND}]},
        "swap_counterparties": [{"sort": "A", "shortName": "甲账户"}, {"sort": "B", "shortName": "乙账户"}],
        "quote_ticker_candidates": [
            {"orderId": SECOND, "orderSeq": 2, "candidates": [{"seq": 1, "code": "MSFT.O", "name": "微软"}]},
            {"orderId": FIRST, "orderSeq": 1, "candidates": [{"seq": 1, "code": "AAPL.O", "name": "苹果"}]}]}


async def test_scoped_counterparty_choices_are_locked():
    """反序输入仍按订单身份写入对应对手，保留选择证据。"""
    data = state("序号2，B；序号1，A")
    choice = counterparty_choice(data)
    result = await swap_apply_picks({**data, "swap_counterparty_picks": choice.model_dump()})
    assert not result.get("error"), result
    assert [r["placeOrderShortname"] for r in result["place_params"]["orderList"]] == ["甲账户", "乙账户"]
    assert result["field_records"]["swap/place_order.orderList.1.placeOrderShortname.selection"].evidence == "序号2，B"


async def test_ticker_choice_uses_order_identity():
    """按第几笔选择不能按候选块位置交叉串单。"""
    data = state("第1笔选标的1；第2笔选标的1")
    choice = ticker_choice(data)
    result = await swap_apply_picks({**data, "swap_ticker_picks": [p.model_dump() for p in choice.picks]})
    assert not result.get("error"), result
    assert [r["placeOrderWindCode"] for r in result["place_params"]["orderList"]] == ["AAPL.O", "MSFT.O"]


@pytest.mark.parametrize("raw,evidence", [("B", "B"), ("帮我决定吧", "选B")])
async def test_unscoped_or_invented_model_pointer_is_rejected(raw, evidence):
    """真实模型指针仍须通过代码来源与范围检查。"""
    result = await swap_apply_picks({**state(raw), "swap_counterparty_picks": {
        "hasSignal": True, "picks": [{"idx": 0, "letter": "B", "evidence": evidence, "confidence": .9}]}})
    assert result.get("error")


@pytest.mark.parametrize("raw", ["序号1选A；序号1选B", "序号3选B"])
def test_conflicting_or_unknown_scope_stops_selection(raw):
    """歧义或不存在的订单选择不能落到默认首笔。"""
    with pytest.raises(ValueError):
        counterparty_choice(state(raw))


def test_all_ticker_choice_cannot_skip_an_order():
    """全部选择缺一笔候选时整批失败，不能静默少提交订单。"""
    data = state("全部订单选标的1")
    data["quote_ticker_candidates"] = data["quote_ticker_candidates"][:1]
    with pytest.raises(ValueError):
        ticker_choice(data)
