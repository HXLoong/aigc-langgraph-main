"""F4.1 shadow_compare 字段级 diff 测试。"""
from __future__ import annotations

import sys
from pathlib import Path

# 让 tests 能 import scripts/ 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.shadow_compare import (
    DEFAULT_IGNORED_PATHS,
    _flatten,
    _normalize_dify,
    _path_matches,
    compare,
)


# ============================================================
# _flatten
# ============================================================


def test_flatten_dict() -> None:
    assert _flatten({"a": 1, "b": {"c": 2}}) == {"a": 1, "b.c": 2}


def test_flatten_list() -> None:
    assert _flatten({"orderList": [{"qty": 100}, {"qty": 200}]}) == {
        "orderList[0].qty": 100,
        "orderList[1].qty": 200,
    }


def test_flatten_nested_list_in_dict() -> None:
    assert _flatten({"a": [[1, 2], [3]]}) == {
        "a[0][0]": 1,
        "a[0][1]": 2,
        "a[1][0]": 3,
    }


def test_flatten_with_prefix() -> None:
    assert _flatten({"k": "v"}, prefix="root") == {"root.k": "v"}


def test_flatten_empty_dict() -> None:
    assert _flatten({}) == {}


# ============================================================
# _path_matches
# ============================================================


def test_path_matches_exact() -> None:
    assert _path_matches("reply_text", {"reply_text"})


def test_path_matches_wildcard() -> None:
    assert _path_matches("place_params.orderList[0].orderId", {"*.orderId"})
    assert _path_matches("orderId", {"*.orderId"})  # 无前缀也匹配


def test_path_matches_negative() -> None:
    assert not _path_matches("place_params.orderList[0].qty", {"*.orderId"})


# ============================================================
# _normalize_dify · 业务对象字段提取
# ============================================================


def test_normalize_extracts_business_objects() -> None:
    resp = {
        "body": {
            "data": {
                "outputs": {
                    "product_type": "swap",
                    "intent": "place_order_request",
                    "place_params": {"expected_action": "place", "orderList": []},
                    "tickers": [{"windCode": "600519.SH"}],
                    "ticker_hitl_candidates": [],
                    "reply_text": "已生成订单",
                }
            }
        }
    }
    norm = _normalize_dify(resp)
    assert norm["product_type"] == "swap"
    assert norm["intent"] == "place_order_request"
    assert norm["place_params"]["expected_action"] == "place"
    assert norm["tickers"] == [{"windCode": "600519.SH"}]
    assert norm["reply_text"] == "已生成订单"


def test_normalize_handles_camelcase_aliases() -> None:
    """Dify 输出可能用 camelCase（productType / placeParams 等）。"""
    resp = {"body": {"data": {"outputs": {"productType": "option", "placeParams": {"x": 1}}}}}
    norm = _normalize_dify(resp)
    assert norm["product_type"] == "option"
    assert norm["place_params"] == {"x": 1}


def test_normalize_missing_outputs_returns_defaults() -> None:
    norm = _normalize_dify({"body": {}})
    assert norm["product_type"] is None
    assert norm["tickers"] == []
    assert norm["place_params"] == {}


# ============================================================
# compare · F4.1 字段级 diff
# ============================================================


def _wrap(outputs: dict) -> dict:
    return {"body": {"data": {"outputs": outputs}}}


def test_compare_equal_simple() -> None:
    lg = _wrap({"product_type": "swap", "intent": "confirm_order"})
    df = _wrap({"product_type": "swap", "intent": "confirm_order"})
    eq, diffs = compare(lg, df)
    assert eq is True
    assert diffs == {}


def test_compare_diff_on_intent() -> None:
    lg = _wrap({"product_type": "swap", "intent": "place_order_request"})
    df = _wrap({"product_type": "swap", "intent": "confirm_order"})
    eq, diffs = compare(lg, df)
    assert eq is False
    assert "intent" in diffs
    assert diffs["intent"]["langgraph"] == "place_order_request"
    assert diffs["intent"]["dify"] == "confirm_order"


def test_compare_diff_on_business_object() -> None:
    """F4.1 关键能力：业务对象字段路径 diff。"""
    lg = _wrap({
        "product_type": "swap",
        "place_params": {"orderList": [{"placeOrderQuantity": 100}]},
    })
    df = _wrap({
        "product_type": "swap",
        "place_params": {"orderList": [{"placeOrderQuantity": 200}]},
    })
    eq, diffs = compare(lg, df)
    assert eq is False
    assert "place_params.orderList[0].placeOrderQuantity" in diffs


def test_compare_ignores_reply_text_by_default() -> None:
    """reply_text 在 DEFAULT_IGNORED_PATHS（渲染层不强 diff）。"""
    lg = _wrap({"product_type": "swap", "reply_text": "确认下单"})
    df = _wrap({"product_type": "swap", "reply_text": "请确认下单"})
    eq, diffs = compare(lg, df)
    assert eq is True
    assert "reply_text" not in diffs


def test_compare_ignores_order_id_by_default() -> None:
    """订单号双侧独立生成，DEFAULT_IGNORED_PATHS 含 *.orderId。"""
    lg = _wrap({"place_params": {"orderList": [{"orderId": "H-LG-001"}]}})
    df = _wrap({"place_params": {"orderList": [{"orderId": "H-DF-002"}]}})
    eq, diffs = compare(lg, df)
    assert eq is True


def test_compare_custom_ignore_path() -> None:
    """自定义忽略字段。"""
    lg = _wrap({"product_type": "swap", "intent": "x"})
    df = _wrap({"product_type": "swap", "intent": "y"})
    eq, diffs = compare(lg, df, ignore_paths={"intent"})
    assert eq is True
    assert "intent" not in diffs


def test_compare_diff_in_tickers_list() -> None:
    lg = _wrap({"tickers": [{"windCode": "600519.SH"}]})
    df = _wrap({"tickers": [{"windCode": "00700.HK"}]})
    eq, diffs = compare(lg, df)
    assert eq is False
    assert "tickers[0].windCode" in diffs


def test_default_ignored_paths_freezeset() -> None:
    """DEFAULT_IGNORED_PATHS 是 frozenset，调用方不能误改全局默认。"""
    assert isinstance(DEFAULT_IGNORED_PATHS, frozenset)
    assert "*.orderId" in DEFAULT_IGNORED_PATHS
    assert "reply_text" in DEFAULT_IGNORED_PATHS
