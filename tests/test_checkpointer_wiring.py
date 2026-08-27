"""#153 裁决落地：AIOMySQLSaver checkpointer 接线到生产（ADR 0009/0021）。

约定：
- `use_mysql_checkpointer=true` → lifespan 初始化 AIOMySQLSaver 并传入 build_main_graph；
  初始化失败直接 raise（显式启用即硬依赖，不静默降级）
- production 环境必须启用——未启用时 lifespan 直接 raise（多轮状态持久化是生产正确性）
- development 默认关闭（本地/CI 测试不依赖 MySQL，避免 checkpoint 脏状态）
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

import app.main as app_main


def _settings(environment: str, use_cp: bool) -> SimpleNamespace:
    return SimpleNamespace(environment=environment, use_mysql_checkpointer=use_cp)


class TestLifespanWiring:
    def test_production_without_checkpointer_fails_fast(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_main, "get_settings", lambda: _settings("production", False))
        with pytest.raises(RuntimeError, match="checkpointer"):
            with TestClient(app_main.app):
                pass

    def test_enabled_but_init_failure_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom() -> None:
            raise ConnectionError("mysql down")

        monkeypatch.setattr(app_main, "get_settings", lambda: _settings("development", True))
        monkeypatch.setattr(app_main, "init_checkpointer", _boom)
        with pytest.raises(ConnectionError):
            with TestClient(app_main.app):
                pass

    def test_enabled_wires_saver_into_graph(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saver = InMemorySaver()

        async def _fake_init() -> InMemorySaver:
            return saver

        async def _fake_close() -> None:
            return None

        monkeypatch.setattr(app_main, "get_settings", lambda: _settings("development", True))
        monkeypatch.setattr(app_main, "init_checkpointer", _fake_init)
        monkeypatch.setattr(app_main, "close_checkpointer", _fake_close)
        with TestClient(app_main.app) as client:
            graph = client.app.state.main_graph
            assert graph.checkpointer is saver

    def test_development_default_off_compiles_without_saver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_main, "get_settings", lambda: _settings("development", False))
        with TestClient(app_main.app) as client:
            assert client.app.state.main_graph.checkpointer is None


def test_settings_field_default_off() -> None:
    """默认关闭——本地/CI 不被 MySQL 依赖绑架；生产由模板显式开启。"""
    from app.config import Settings

    assert Settings.model_fields["use_mysql_checkpointer"].default is False
