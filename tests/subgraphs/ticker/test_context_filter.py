"""互换显式启用的候选上下文去噪，不按数字值全局删除。"""
from __future__ import annotations

import pytest

from app.subgraphs.ticker.tools import tokenize

SHORTNAME = "11125测试短名（张天琪专用）"
REPORTS = [
    "新增指令：标的：NVDA方向：卖出股份数量：1453股建仓方式：pov跟量7%，"
    "不限价备注：根据市场成交量成交，标的：TSM方向：卖出股份数量：3071股"
    "建仓方式：pov跟量7%，不限价备注：根据市场成交量成交 " + SHORTNAME,
    "NVDA 卖出 1,453 股，均价 883.9758 TSM 卖出 3,071 股，均价 139.8888 " + SHORTNAME,
]


@pytest.mark.parametrize("raw", REPORTS, ids=["report-pov", "report-average-price"])
def test_report_quantities_prices_and_full_counterparty_are_not_candidates(raw: str) -> None:
    # langchain @tool 在未实现过滤参数时会忽略额外参数，因此 RED 捕获真实噪音。
    candidates = tokenize.invoke({
        "raw_text": raw, "filter_order_context": True, "counterparty_shortnames": [SHORTNAME],
    })
    assert any("NVDA" in candidate for candidate in candidates)
    assert any("TSM" in candidate for candidate in candidates)
    assert not any(char.isdigit() for candidate in candidates for char in candidate), candidates
    assert not any("张天琪" in candidate or "专用" in candidate for candidate in candidates)


def test_context_filter_is_disabled_by_default() -> None:
    raw = "TSM 3071股 均价139.8888 " + SHORTNAME
    current = tokenize.invoke({"raw_text": raw})
    explicit_off = tokenize.invoke({
        "raw_text": raw, "filter_order_context": False, "counterparty_shortnames": [SHORTNAME],
    })
    assert current == explicit_off
    assert "3071" in current
    assert "8888" in current
    assert "11125" in current


@pytest.mark.parametrize(("raw", "kept", "removed"), [
    ("600519 3071股 限价883.9758", ["600519"], ["3071", "883.", "9758"]),
    ("数量600519.SH 3071股", ["600519.SH"], ["3071"]),
    ("标的代码：1000股 数量2000股", ["1000"], ["2000"]),
    ("600519.SH数量600519股价格139.8888", ["600519.SH"], ["8888"]),
    ("标的：600519数量600519均价600519", ["600519"], []),
    ("中证1000 中证2000 沪深300 上证50 50ETF IF2503 数量1000",
     ["中证1000", "中证2000", "沪深300", "上证50", "50ETF", "2503", "IF"], []),
    ("TSM2625股均价139.8888", ["TSM"], ["2625", "8888"]),
    ("NVDA数量1,453股TSM数量3，071股均价1,234.5678", ["NVDA", "TSM"],
     ["1453", "3071", "5678", "453", "071"]),
    ("TSM 委托数量3071 委托价格139.8888 POV比例12.3456％ 跟量3456",
     ["TSM"], ["3071", "8888", "3456"]),
    ("TSM @139.8888 数量1.453万股", ["TSM"], ["8888", "453"]),
    ("TSM 3071 883.9758", ["TSM", "3071", "9758"], []),
    ("NVDA 不限价3071", ["NVDA", "3071"], []),
    ("NVDA 1000股 账号1453", ["NVDA"], ["1000", "1453"]),
    ("NVDA 1000股 1453", ["NVDA", "1453"], ["1000"]),
    ("标的代码1453 数量1453 账号1453", ["1453"], []),
    ("中证1000股指期货 1000股", ["中证1000股指期货"], []),
    ("NVDA 883.9758美元 TSM 139.8888元", ["NVDA", "TSM"], ["9758", "8888"]),
])
def test_context_filter_preserves_ticker_positions(raw, kept, removed) -> None:
    candidates = tokenize.invoke({
        "raw_text": raw, "filter_order_context": True, "counterparty_shortnames": ["1453"],
    })
    for value in kept:
        assert any(value in candidate for candidate in candidates), candidates
    for value in removed:
        assert not any(value in candidate for candidate in candidates), candidates


def test_explicit_ticker_is_kept_when_its_name_is_also_a_counterparty() -> None:
    candidates = tokenize.invoke({
        "raw_text": "标的代码：NVDA 1000股 对手：测试账户",
        "filter_order_context": True, "counterparty_shortnames": ["NVDA", "测试账户"],
    })
    assert any("NVDA" in candidate for candidate in candidates)
    assert not any("测试账户" in candidate for candidate in candidates)


def test_numeric_counterparty_prefix_cannot_mask_a_different_account() -> None:
    raw = "NVDA 账号1453.9758"
    assert tokenize.invoke({
        "raw_text": raw, "filter_order_context": True, "counterparty_shortnames": ["1453"],
    }) == tokenize.invoke({"raw_text": raw})


def test_same_value_in_ticker_quantity_and_price_is_filtered_by_position() -> None:
    assert tokenize.invoke({
        "raw_text": "1453 1453股 均价1453", "filter_order_context": True,
    }) == ["1453"]
