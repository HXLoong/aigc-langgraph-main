"""app/domain/sanitize.py：三个子图前置清洗共用的 null 字面量递归核心。"""
from __future__ import annotations

from app.domain.sanitize import strip_null_literals


def test_strips_null_literals_recursively() -> None:
    value = {"a": " NULL ", "b": ["x", "null", None], "c": {"d": "null", "e": 1}}
    assert strip_null_literals(value) == {"a": None, "b": ["x"], "c": {"d": None, "e": 1}}


def test_custom_literals_and_input_not_mutated() -> None:
    value = {"a": "n/a", "b": "null"}
    assert strip_null_literals(value, frozenset({"n/a"})) == {"a": None, "b": "null"}
    assert value == {"a": "n/a", "b": "null"}


def test_subgraph_wrappers_share_core() -> None:
    from app.subgraphs.close.aggregate import sanitize_close_order_req_vo
    from app.subgraphs.option.sanitize import sanitize_order_list as option_sanitize
    from app.subgraphs.swap.prewash import sanitize_order_list as swap_sanitize

    orders = [{"price": "null", "tags": ["null", "a"]}]
    assert option_sanitize(orders) == swap_sanitize(orders) == [{"price": None, "tags": ["a"]}]
    assert sanitize_close_order_req_vo({"x": "null"}, "") == {"x": None}
