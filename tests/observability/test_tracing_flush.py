"""lifespan 关闭段 flush LangFuse（ADR 0024 D5：滚动更新 / SIGTERM 不丢尾部 trace）。"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.observability import tracing


def test_flush_calls_client_flush_when_present(monkeypatch) -> None:
    client = MagicMock()
    monkeypatch.setattr(tracing, "_langfuse_client", client)
    tracing.flush()
    client.flush.assert_called_once()


def test_flush_is_noop_without_client(monkeypatch) -> None:
    monkeypatch.setattr(tracing, "_langfuse_client", None)
    tracing.flush()  # 不抛
