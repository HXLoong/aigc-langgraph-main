"""sanitize_order_list 边界测试（期权开仓前置清洗规则）。"""
from __future__ import annotations

from app.subgraphs.option.sanitize import sanitize_order_list


class TestSanitizeOrderList:
    def test_empty_input(self) -> None:
        assert sanitize_order_list(None) == []
        assert sanitize_order_list([]) == []

    def test_null_literal_string_becomes_none(self) -> None:
        out = sanitize_order_list([{"orderId": "Q-1", "shortName": "null"}])
        assert out == [{"orderId": "Q-1", "shortName": None}]

    def test_null_literal_case_insensitive_and_whitespace(self) -> None:
        out = sanitize_order_list(
            [{"shortName": "NULL"}, {"shortName": " Null "}]
        )
        assert out == [{"shortName": None}, {"shortName": None}]

    def test_non_null_strings_untouched(self) -> None:
        out = sanitize_order_list([{"stockCode": "600519.SH"}])
        assert out == [{"stockCode": "600519.SH"}]

    def test_order_item_itself_not_dropped(self) -> None:
        """订单条目本身不会因为字段被清成 None 而从列表消失（条目数由用户输入决定）。"""
        out = sanitize_order_list([{"orderId": "null", "stockCode": "null"}])
        assert len(out) == 1
        assert out[0] == {"orderId": None, "stockCode": None}

    def test_nested_list_drops_null_elements(self) -> None:
        out = sanitize_order_list(
            [{"tags": ["a", "null", "b", "NULL"]}]
        )
        assert out == [{"tags": ["a", "b"]}]

    def test_non_string_values_untouched(self) -> None:
        out = sanitize_order_list(
            [{"limitPrice": 9.1, "povRatio": 25, "hasFastExecutionIntent": False}]
        )
        assert out == [
            {"limitPrice": 9.1, "povRatio": 25, "hasFastExecutionIntent": False}
        ]

    def test_multiple_orders(self) -> None:
        out = sanitize_order_list(
            [{"orderId": "Q-A"}, {"orderId": "null"}, {"orderId": "Q-B"}]
        )
        assert out == [
            {"orderId": "Q-A"},
            {"orderId": None},
            {"orderId": "Q-B"},
        ]
