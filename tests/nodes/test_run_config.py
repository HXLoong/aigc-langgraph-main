"""API 层 graph 调用 config 构造测试(架构体检改进 A:显式 recursion_limit)。"""
from __future__ import annotations

from app.api.routes import GRAPH_RECURSION_LIMIT, _build_run_config


class TestBuildRunConfig:
    def test_recursion_limit_set(self):
        cfg = _build_run_config(conversation_id="c-1", trace_id="t-1")
        assert cfg["recursion_limit"] == GRAPH_RECURSION_LIMIT
        assert GRAPH_RECURSION_LIMIT >= 25  # CLAUDE.md 指引下限

    def test_thread_and_trace(self):
        cfg = _build_run_config(conversation_id="c-9", trace_id="t-9")
        assert cfg["configurable"]["thread_id"] == "c-9"
        assert cfg["metadata"]["trace_id"] == "t-9"
