"""主图状态与产品条件路由的纯函数单测（此前只有入口 `_route_entry` 与 cascade e2e 覆盖）。

条件路由必须是纯函数（.claude/rules/langgraph-patterns.md）：错误优先转 fallback，
不做副作用；这里逐条钉住优先级与边界值。
"""
from __future__ import annotations

import pytest

from app.graph.main import _route_after_ingest, _route_after_intent
from app.graph.state import ErrorInfo

_ERR = ErrorInfo(node="n", type="RuntimeError", message="x")


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({}, "entry_route"),
        ({"session_status": "active"}, "entry_route"),
        ({"session_status": "expired"}, "render"),
        ({"error": _ERR}, "render"),
        ({"error": _ERR, "session_status": "active"}, "render"),
    ],
    ids=["fresh", "active", "expired", "error", "error_and_active"],
)
def test_route_after_ingest(state: dict, expected: str) -> None:
    assert _route_after_ingest(state) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"product_type": "swap"}, "swap"),
        ({"product_type": "option"}, "option"),
        ({"product_type": "option_close"}, "option_close"),
        ({"product_type": "unknown"}, "fallback"),
        ({}, "fallback"),
        ({"product_type": "swap", "error": _ERR}, "fallback"),
    ],
    ids=["swap", "option", "option_close", "unknown", "missing", "error_wins"],
)
def test_route_after_intent(state: dict, expected: str) -> None:
    assert _route_after_intent(state) == expected
