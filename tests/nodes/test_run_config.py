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


class TestLangfuseDimensions:
    """ADR 0024 D5：config.metadata 必须携带 LangFuse 会话 / 用户 / 标签维度，
    否则多轮在 LangFuse 里是 N 条互不关联的 trace。"""

    def test_session_and_user(self):
        cfg = _build_run_config(
            conversation_id="c-9", trace_id="t-9", user_id="u-1", environment="staging"
        )
        md = cfg["metadata"]
        assert md["langfuse_session_id"] == "c-9"
        assert md["langfuse_user_id"] == "u-1"
        assert "staging" in md["langfuse_tags"]

    def test_user_optional(self):
        cfg = _build_run_config(conversation_id="c-9", trace_id="t-9")
        assert "langfuse_user_id" not in cfg["metadata"]
        assert cfg["metadata"]["langfuse_session_id"] == "c-9"
