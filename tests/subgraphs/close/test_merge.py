"""close.place_close 链 · 合并输出纯函数测试。

平仓参数合并输出规则（原 DSL v2「平仓参数提取-合并输出」代码节点，现以本仓实现为准）。
"""
from __future__ import annotations

from app.subgraphs.close.merge import merge_close_orders


class TestHoldingListPath:
    """messageType != "close_result"：直接用 LLM 输出（过滤空条目）。"""

    def test_returns_llm_orders_with_order_id(self) -> None:
        llm_orders = [{"orderId": "CO-A", "closeOrderType": "市价单"}]
        result = merge_close_orders("holding_list", [], llm_orders)
        assert result == llm_orders

    def test_filters_out_orders_without_any_id(self) -> None:
        llm_orders = [
            {"orderId": "CO-A"},
            {"orderId": None, "internalTradeId": None},
        ]
        result = merge_close_orders("holding_list", [], llm_orders)
        assert len(result) == 1
        assert result[0]["orderId"] == "CO-A"

    def test_keeps_order_with_only_internal_trade_id(self) -> None:
        llm_orders = [{"orderId": None, "internalTradeId": "OPT-AAA"}]
        result = merge_close_orders("holding_list", [], llm_orders)
        assert result == llm_orders

    def test_ignores_success_orders_on_holding_list_path(self) -> None:
        success = [{"orderId": "CO-IGNORED"}]
        llm_orders = [{"orderId": "CO-A"}]
        result = merge_close_orders("holding_list", success, llm_orders)
        assert result == llm_orders


class TestCloseResultPath:
    """messageType == "close_result"：成功订单 + LLM 提取订单合并，同 id 以 LLM 为准。"""

    def test_merges_success_and_llm_orders(self) -> None:
        success = [{"orderId": "CO-A", "closeOrderType": None}]
        llm_orders = [{"orderId": "CO-B", "closeOrderType": "限价单"}]
        result = merge_close_orders("close_result", success, llm_orders)
        ids = {o["orderId"] for o in result}
        assert ids == {"CO-A", "CO-B"}

    def test_llm_order_overrides_same_id_success_order(self) -> None:
        success = [{"orderId": "CO-A", "closeOrderType": None}]
        llm_orders = [{"orderId": "CO-A", "closeOrderType": "限价单", "closeOrderPrice": 10}]
        result = merge_close_orders("close_result", success, llm_orders)
        assert len(result) == 1
        assert result[0]["closeOrderType"] == "限价单"
        assert result[0]["closeOrderPrice"] == 10

    def test_filters_out_entries_without_any_id(self) -> None:
        success = [{"orderId": None}]
        llm_orders = [{"orderId": None, "internalTradeId": None}]
        result = merge_close_orders("close_result", success, llm_orders)
        assert result == []

    def test_empty_inputs_yield_empty_list(self) -> None:
        assert merge_close_orders("close_result", None, None) == []


__all__: list[str] = []
