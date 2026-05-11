"""cascade 防御工具测试（CLAUDE.md 核心原则第 8 条）。"""
from __future__ import annotations

import pytest

from app.graph.cascade import has_error, with_cascade_guard
from app.graph.state import ErrorInfo


def test_has_error_when_no_error_field() -> None:
    assert has_error({}) is False


def test_has_error_when_error_field_none() -> None:
    assert has_error({"error": None}) is False


def test_has_error_when_error_present() -> None:
    state = {"error": ErrorInfo(node="x", type="ValueError", message="oops")}
    assert has_error(state) is True


def test_with_cascade_guard_passthrough_no_error() -> None:
    router = with_cascade_guard("swap.place_order")
    assert router({}) == "swap.place_order"


def test_with_cascade_guard_routes_to_fallback_on_error() -> None:
    router = with_cascade_guard("swap.place_order")
    state = {"error": ErrorInfo(node="swap.intent", type="x", message="y")}
    assert router(state) == "fallback"


def test_with_cascade_guard_custom_fallback_name() -> None:
    router = with_cascade_guard("next", fallback_node="custom_fb")
    state = {"error": ErrorInfo(node="x", type="x", message="y")}
    assert router(state) == "custom_fb"


@pytest.mark.parametrize(
    "next_node,fallback_node",
    [
        ("swap.place_order", "fallback"),
        ("option.intent", "render"),
        ("close.holding_query", "error_handler"),
    ],
)
def test_with_cascade_guard_router_signature(
    next_node: str, fallback_node: str
) -> None:
    """生成的 router 是单参（state）函数，返回 str。"""
    router = with_cascade_guard(next_node, fallback_node=fallback_node)
    assert callable(router)
    assert router({}) == next_node
