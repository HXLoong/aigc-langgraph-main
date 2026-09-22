"""swap.prewash · 互换开仓-前置清洗 测试（确定性清洗规则，代码为真源）。

覆盖 `app/subgraphs/swap/prewash.py::sanitize_order_list`，在
`app/subgraphs/swap/backend.py:98` 由 `call_swap_backend` 对 6 个意图统一调用一次
（「模型数据聚合 → 前置清洗 → 互换开仓」链路上的单一清洗落点）。

对齐参考：`tests/subgraphs/option/test_sanitize.py`（同一清洗语义的另一份实现）。
测试方法：G1 纯函数确定性。
"""
from __future__ import annotations

from app.subgraphs.swap.prewash import sanitize_order_list


class TestSanitizeOrderList:
    def test_none_returns_empty_list(self) -> None:
        assert sanitize_order_list(None) == []

    def test_empty_list(self) -> None:
        assert sanitize_order_list([]) == []

    def test_null_literal_string_becomes_none(self) -> None:
        out = sanitize_order_list([{"orderId": "H-1", "placeOrderShortname": "null"}])
        assert out == [{"orderId": "H-1", "placeOrderShortname": None}]

    def test_null_literal_case_insensitive_and_whitespace(self) -> None:
        """'NULL' / ' Null ' / '\tnull\n' 都算空值（strip + lower 比较）。"""
        out = sanitize_order_list(
            [
                {"a": "NULL"},
                {"a": " Null "},
                {"a": "\tnull\n"},
            ]
        )
        assert out == [{"a": None}, {"a": None}, {"a": None}]

    def test_non_null_strings_untouched(self) -> None:
        out = sanitize_order_list([{"placeOrderWindCode": "600519.SH"}])
        assert out == [{"placeOrderWindCode": "600519.SH"}]

    def test_order_item_itself_not_dropped(self) -> None:
        """订单条目本身不会因为字段被清成 None 而从列表消失（条目数由用户输入决定）。"""
        out = sanitize_order_list(
            [{"orderId": "null", "placeOrderWindCode": "null"}]
        )
        assert len(out) == 1
        assert out[0] == {"orderId": None, "placeOrderWindCode": None}

    def test_nested_list_drops_null_elements(self) -> None:
        out = sanitize_order_list([{"tags": ["a", "null", "b", "NULL"]}])
        assert out == [{"tags": ["a", "b"]}]

    def test_non_string_values_untouched(self) -> None:
        """int / float / bool / None 原样保留（None 不参与字面量比较）。"""
        out = sanitize_order_list(
            [
                {
                    "placeOrderQuantity": 1000,
                    "placeOrderPrice": 18.12,
                    "hasFastExecutionIntent": False,
                    "orderId": None,
                }
            ]
        )
        assert out == [
            {
                "placeOrderQuantity": 1000,
                "placeOrderPrice": 18.12,
                "hasFastExecutionIntent": False,
                "orderId": None,
            }
        ]

    def test_multiple_orders(self) -> None:
        out = sanitize_order_list(
            [
                {"orderId": "H-A"},
                {"orderId": "null"},
                {"orderId": "H-B"},
            ]
        )
        assert out == [
            {"orderId": "H-A"},
            {"orderId": None},
            {"orderId": "H-B"},
        ]

    def test_nested_dict_recursion(self) -> None:
        out = sanitize_order_list(
            [{"outer": {"inner": "null", "keep": "x"}}]
        )
        assert out == [{"outer": {"inner": None, "keep": "x"}}]

    def test_custom_null_literals(self) -> None:
        """null_literals 可覆盖默认 {'null'}（空值字面量清单可配置）。"""
        out = sanitize_order_list(
            [{"a": "none", "b": "null"}],
            null_literals=frozenset({"none"}),
        )
        assert out == [{"a": None, "b": "null"}]

    def test_does_not_mutate_input(self) -> None:
        """返回新对象，入参保持原样（避免 checkpoint 里已存 state 被就地改）。"""
        original = [{"orderId": "H-1", "placeOrderShortname": "null"}]
        out = sanitize_order_list(original)
        assert original == [{"orderId": "H-1", "placeOrderShortname": "null"}]
        assert out == [{"orderId": "H-1", "placeOrderShortname": None}]
        assert out[0] is not original[0]

    def test_realistic_swap_order_item(self) -> None:
        """真实 swap orderList 形态：混合脏值与正常值。"""
        out = sanitize_order_list(
            [
                {
                    "orderId": None,
                    "placeOrderWindCode": "600519.SH",
                    "placeOrderTransactionType": "A_SHARE",
                    "placeOrderQuantity": 100,
                    "placeOrderOrderDirection": "BUY",
                    "placeOrderPriceType": "LimitOrder",
                    "placeOrderAlgorithmType": "null",
                    "placeOrderPrice": 18.12,
                    "placeOrderPovPercent": None,
                    "placeOrderShortname": "11125测试短名（张天琪专用）",
                }
            ]
        )
        assert out == [
            {
                "orderId": None,
                "placeOrderWindCode": "600519.SH",
                "placeOrderTransactionType": "A_SHARE",
                "placeOrderQuantity": 100,
                "placeOrderOrderDirection": "BUY",
                "placeOrderPriceType": "LimitOrder",
                "placeOrderAlgorithmType": None,
                "placeOrderPrice": 18.12,
                "placeOrderPovPercent": None,
                "placeOrderShortname": "11125测试短名（张天琪专用）",
            }
        ]
