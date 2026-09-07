"""close 子图 · 参数聚合 + 前置清洗纯函数测试。

对齐 Dify `期权平仓-参数聚合` + `期权平仓-前置清洗`（spec/code_nodes/两者）。
"""
from __future__ import annotations

from app.subgraphs.close.aggregate import (
    build_close_order_req_vo,
    sanitize_close_order_req_vo,
)


class TestBuildCloseOrderReqVo:
    def test_all_defaults_when_nothing_passed(self) -> None:
        vo = build_close_order_req_vo()
        assert vo == {
            "contractQuery": {
                "insFamilyList": [],
                "contractTypeList": [],
                "allowCloseOut": True,
                "internalTradeIdList": [],
                "keyCtptyIdList": [],
                "underlyingInsIdList": [],
                "underlyingInsNameList": [],
            },
            "closeOrderList": [],
            "confirmOrderNoList": [],
            "cancelOrderNoList": [],
            "confirmCancelOrderNoList": [],
            "queryOrderNoList": [],
        }

    def test_closeable_only_false_overrides_default_true(self) -> None:
        vo = build_close_order_req_vo(closeable_only=False)
        assert vo["contractQuery"]["allowCloseOut"] is False

    def test_close_order_list_keeps_dict_items_only(self) -> None:
        vo = build_close_order_req_vo(
            close_order_list=[{"orderId": "CO-A"}, "garbage", None, 42]
        )
        assert vo["closeOrderList"] == [{"orderId": "CO-A"}]

    def test_str_list_fields_filter_empty_and_non_str(self) -> None:
        vo = build_close_order_req_vo(
            confirm_order_no_list=["CO-A", "", "  ", None, 1, "CO-B"]
        )
        assert vo["confirmOrderNoList"] == ["CO-A", "CO-B"]

    def test_key_ctpty_id_list_not_filtered_by_type(self) -> None:
        """对齐 JS 原版：keyCtptyIdList 只判 isArray，不按元素类型过滤。"""
        vo = build_close_order_req_vo(key_ctpty_id_list=[1, 2, 3])
        assert vo["contractQuery"]["keyCtptyIdList"] == [1, 2, 3]

    def test_populates_only_relevant_field_others_default(self) -> None:
        """每个 close 意图分支只填自己的字段，其余保持默认——与 6 分支各自独立
        调用 aggregate 后再各自清洗提交的行为等价。"""
        vo = build_close_order_req_vo(cancel_order_no_list=["CO-X"])
        assert vo["cancelOrderNoList"] == ["CO-X"]
        assert vo["closeOrderList"] == []
        assert vo["confirmOrderNoList"] == []


class TestSanitizeCloseOrderReqVo:
    def test_null_literal_string_becomes_none(self) -> None:
        cleaned = sanitize_close_order_req_vo({"a": "null", "b": "keep"})
        assert cleaned == {"a": None, "b": "keep"}

    def test_null_literal_case_insensitive(self) -> None:
        cleaned = sanitize_close_order_req_vo({"a": "NULL", "b": "Null"})
        assert cleaned == {"a": None, "b": None}

    def test_null_elements_dropped_from_list(self) -> None:
        cleaned = sanitize_close_order_req_vo({"list": ["keep", "null", "also"]})
        assert cleaned == {"list": ["keep", "also"]}

    def test_recurses_into_nested_dict_and_list(self) -> None:
        raw = {
            "contractQuery": {"underlyingInsIdList": ["null", "600000.SH"]},
            "closeOrderList": [{"orderId": "CO-A", "closeOrderPrice": "null"}],
        }
        cleaned = sanitize_close_order_req_vo(raw)
        assert cleaned["contractQuery"]["underlyingInsIdList"] == ["600000.SH"]
        assert cleaned["closeOrderList"][0]["closeOrderPrice"] is None
        assert cleaned["closeOrderList"][0]["orderId"] == "CO-A"

    def test_non_string_values_untouched(self) -> None:
        cleaned = sanitize_close_order_req_vo({"n": 1, "b": True, "f": None})
        assert cleaned == {"n": 1, "b": True, "f": None}

    def test_custom_null_literals_env_override(self) -> None:
        cleaned = sanitize_close_order_req_vo({"a": "N/A"}, null_literals="n/a,none")
        assert cleaned == {"a": None}

    def test_non_dict_top_level_returns_empty_dict(self) -> None:
        assert sanitize_close_order_req_vo("not-a-dict") == {}  # type: ignore[arg-type]


__all__: list[str] = []
