"""swap 订单号确定性提取器单测(瘦身 P1:5 个订单号节点去 LLM 化)。

行为对照原提示词规约:
- cancel:raw 明确指定的单号优先;否则 quote 中全部;都无 → [None]
- query:raw 优先,否则 quote;都无 → [None]
- confirm_order:quote 中全部(按首现顺序去重);quote 无则 raw;都无 → [None]
- confirm_cancel / confirm_modify:quote 优先取全部,否则 raw;都无 → [None]
"""
from __future__ import annotations

from app.subgraphs.swap.order_id import (
    extract_for_cancel,
    extract_for_confirm_order,
    extract_for_confirm_single,
    extract_for_query,
    extract_order_ids,
)

Q1 = "H-20260101-0000000001"
Q2 = "H-20260101-0000000002"
R1 = "H-20260202-0000000009"


class TestExtractOrderIds:
    def test_ordered_dedup(self):
        text = f"单号:{Q1} 与 {Q2},再次 {Q1}"
        assert extract_order_ids(text) == [Q1, Q2]

    def test_format_strict(self):
        # 8 位日期 + 10 位数字;不匹配的形态不提取
        assert extract_order_ids("H-2026-01 H-20260101-123 OPT-20260101-0000000001") == []

    def test_none_and_empty(self):
        assert extract_order_ids(None) == []
        assert extract_order_ids("") == []


class TestCancel:
    def test_raw_explicit_wins(self):
        out = extract_for_cancel(raw=f"撤掉 {R1}", quote=f"单号:{Q1}\n单号:{Q2}")
        assert out == [R1]

    def test_quote_all_when_raw_bare(self):
        out = extract_for_cancel(raw="全部撤单", quote=f"单号:{Q1}\n单号:{Q2}")
        assert out == [Q1, Q2]

    def test_none(self):
        assert extract_for_cancel(raw="撤单", quote="") == [None]


class TestQuery:
    def test_raw_first(self):
        assert extract_for_query(raw=f"查 {R1}", quote=f"单号:{Q1}") == [R1]

    def test_quote_fallback(self):
        assert extract_for_query(raw="订单怎么样了", quote=f"单号:{Q1}") == [Q1]

    def test_none(self):
        assert extract_for_query(raw="查订单", quote=None) == [None]


class TestConfirmOrder:
    def test_all_from_quote_ordered_dedup(self):
        quote = f"订单{Q1}(序号1)\n订单{Q2}(序号2)\n又见 {Q1}"
        assert extract_for_confirm_order(raw="确认下单", quote=quote) == [Q1, Q2]

    def test_raw_fallback(self):
        assert extract_for_confirm_order(raw=f"确认下单 {R1}", quote="") == [R1]

    def test_none(self):
        assert extract_for_confirm_order(raw="确认下单", quote="") == [None]


class TestConfirmSingle:
    def test_quote_first(self):
        assert extract_for_confirm_single(raw=f"确认撤单 {R1}", quote=f"单号:{Q1}") == [Q1]

    def test_raw_fallback(self):
        assert extract_for_confirm_single(raw=f"确认撤单 {R1}", quote="") == [R1]

    def test_none(self):
        assert extract_for_confirm_single(raw="确认撤单", quote="") == [None]
