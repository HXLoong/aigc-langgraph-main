"""cascade 防御工具测试（CLAUDE.md 核心原则第 8 条）。"""
from __future__ import annotations

from app.graph.cascade import has_error
from app.graph.state import ErrorInfo


def test_has_error_when_no_error_field() -> None:
    assert has_error({}) is False


def test_has_error_when_error_field_none() -> None:
    assert has_error({"error": None}) is False


def test_has_error_when_error_present() -> None:
    state = {"error": ErrorInfo(node="x", type="ValueError", message="oops")}
    assert has_error(state) is True
