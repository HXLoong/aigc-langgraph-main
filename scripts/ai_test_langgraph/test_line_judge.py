"""line_judge 启用开关契约（离线；不触发 LLM 网络调用）。"""
from __future__ import annotations

from line_judge import build_line_judge


def test_disabled_flag_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("AI_TEST_LLM_JUDGE", "0")
    assert build_line_judge() is None


def test_disabled_flag_accepts_false_values(monkeypatch) -> None:
    for value in ("false", "off", "no", "FALSE"):
        monkeypatch.setenv("AI_TEST_LLM_JUDGE", value)
        assert build_line_judge() is None
