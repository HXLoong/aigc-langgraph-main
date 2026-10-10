"""app/subgraphs/common.py：三个子图共用的意图分发与 unknown 兜底骨架。"""
from __future__ import annotations

import pytest

from app.graph.state import ErrorInfo
from app.subgraphs.common import intent_router, make_unknown_node

_TABLE = {"a": "node_a", "b": "node_b"}


def test_intent_router_dispatches_and_falls_back() -> None:
    route = intent_router(_TABLE, "x_unknown")
    assert route({"intent": "a"}) == "node_a"
    assert route({"intent": "zzz"}) == "x_unknown"
    assert route({}) == "x_unknown"
    assert route({"intent": "a", "error": ErrorInfo(node="n", type="T", message="m")}) == "x_unknown"


async def test_unknown_node_named_after_product() -> None:
    node = make_unknown_node("x_unknown")
    out = await node({"intent": "weird"})
    assert [(e.node, e.decision) for e in out["trace"]] == [("x_unknown", "unhandled_intent=weird")]


@pytest.mark.parametrize(("module", "name"), [
    ("app.subgraphs.swap.graph", "swap_unknown"),
    ("app.subgraphs.option.graph", "option_unknown"),
    ("app.subgraphs.close.graph", "close_unknown"),
])
def test_each_subgraph_exposes_named_unknown_node(module: str, name: str) -> None:
    from importlib import import_module

    assert getattr(import_module(module), name).__name__ == name
