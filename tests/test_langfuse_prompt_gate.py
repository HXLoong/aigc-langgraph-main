"""#155 裁决落地：LangFuse 提示词生产硬闸门 + 降级告警（ADR 0014 D3-2）。

- production + use_langfuse_prompts=true → load_prompt 直接 raise（防绕过 git PR 审计）
- 非生产环境拉取失败 → warning 级日志（原为 debug 静默）后回退本地
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import app.prompts as prompts_mod
from app.prompts import clear_cache, load_prompt


def _settings(environment: str, use_langfuse_prompts: bool) -> SimpleNamespace:
    return SimpleNamespace(
        enable_langfuse=True,
        use_langfuse_prompts=use_langfuse_prompts,
        environment=environment,
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    # load_prompt 在函数体内 `from app.config import get_settings`，patch 定义处即可
    monkeypatch.setattr("app.config.get_settings", lambda: settings)


class TestProductionGate:
    def test_production_with_langfuse_prompts_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, _settings("production", True))
        with pytest.raises(RuntimeError, match="生产环境"):
            load_prompt("swap", "intent")

    def test_production_without_flag_loads_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, _settings("production", False))
        p = load_prompt("swap", "intent")
        assert p.system

    def test_development_with_flag_falls_back_to_local(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, _settings("development", True))
        monkeypatch.setattr(prompts_mod, "_load_from_langfuse", lambda c, n: None)
        p = load_prompt("swap", "intent")
        assert p.system


class TestFallbackWarning:
    def test_langfuse_failure_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """拉取抛异常时必须 warning 级（原 debug 静默会掩盖版本错配）。"""

        class _Boom:
            def get_prompt(self, *a, **k):
                raise ConnectionError("langfuse down")

        monkeypatch.setattr(prompts_mod, "_get_langfuse_client", lambda: _Boom())
        with caplog.at_level(logging.WARNING, logger="app.prompts"):
            result = prompts_mod._load_from_langfuse("swap", "intent")
        assert result is None
        assert any("回退本地" in r.message for r in caplog.records)
