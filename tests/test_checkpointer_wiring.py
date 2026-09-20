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
    return SimpleNamespace(
        environment=environment, use_mysql_checkpointer=use_cp, backend_timeout_seconds=30.0,
        log_level="INFO", log_format="console",
    )


class TestLifespanWiring:
    def test_production_without_checkpointer_fails_fast(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(app_main, "get_settings", lambda: _settings("production", False))
        with pytest.raises(RuntimeError, match="checkpointer"), TestClient(app_main.app):
            pass

    def test_enabled_but_init_failure_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom() -> None:
            raise ConnectionError("mysql down")

        monkeypatch.setattr(app_main, "get_settings", lambda: _settings("development", True))
        monkeypatch.setattr(app_main, "init_checkpointer", _boom)
        with pytest.raises(ConnectionError), TestClient(app_main.app):
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


class _FakePool:
    def __init__(self) -> None:
        self.closed = False
        self.wait_closed_called = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.wait_closed_called = True


class _FakeSaver:
    instances: list[_FakeSaver] = []
    # 真实 saver 的连接串解析是纯函数，直接复用
    from langgraph.checkpoint.mysql.aio import AIOMySQLSaver as _Real

    parse_conn_string = staticmethod(_Real.parse_conn_string)

    def __init__(self, conn, serde=None) -> None:  # type: ignore[no-untyped-def]
        self.conn = conn
        self.serde = serde
        self.setup_called = False
        _FakeSaver.instances.append(self)

    async def setup(self) -> None:
        self.setup_called = True


def _pool_settings() -> SimpleNamespace:
    return SimpleNamespace(
        mysql_uri="mysql://u:p@h:3307/db",
        checkpoint_pool_minsize=2,
        checkpoint_pool_maxsize=7,
        checkpoint_pool_recycle_seconds=1234,
    )


@pytest.mark.asyncio
async def test_init_checkpointer_uses_connection_pool_with_recycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0024 D4：from_conn_string 只持有一条连接、无重连（saver 内部一把锁串行化全部 IO，
    连接被 wait_timeout 杀掉后全站失忆）。生产必须用 aiomysql 连接池 + pool_recycle。"""
    from unittest.mock import AsyncMock

    import app.checkpointer.factory as factory

    pool = _FakePool()
    create_pool = AsyncMock(return_value=pool)
    _FakeSaver.instances.clear()
    monkeypatch.setattr(factory, "get_settings", _pool_settings)
    monkeypatch.setattr(factory.aiomysql, "create_pool", create_pool)
    monkeypatch.setattr(factory, "AIOMySQLSaver", _FakeSaver)

    saver = await factory.init_checkpointer()
    try:
        kwargs = create_pool.call_args.kwargs
        assert kwargs["host"] == "h" and kwargs["port"] == 3307 and kwargs["db"] == "db"
        assert kwargs["autocommit"] is True
        assert kwargs["charset"] == "utf8mb4"
        assert kwargs["init_command"] == "SET NAMES utf8mb4 COLLATE utf8mb4_general_ci"
        assert kwargs["minsize"] == 2 and kwargs["maxsize"] == 7
        assert kwargs["pool_recycle"] == 1234
        assert saver.conn is pool, "saver 必须持有连接池而不是单条连接"
        assert saver.setup_called
        allowed = {name for _mod, name in saver.serde._allowed_msgpack_modules}  # noqa: SLF001
        assert {"TickerCandidate", "Message", "TraceEntry"} <= allowed
    finally:
        await factory.close_checkpointer()
    assert pool.closed and pool.wait_closed_called


@pytest.mark.asyncio
async def test_probe_checkpointer_uses_saver_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """/ready 的 mysql 探针必须打 saver 自己的连接池，而不是另开一条新连接。"""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    import app.checkpointer.factory as factory

    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=(1,))

    @asynccontextmanager
    async def _cursor():  # type: ignore[no-untyped-def]
        yield cur

    conn = MagicMock()
    conn.cursor = _cursor

    @asynccontextmanager
    async def _acquire():  # type: ignore[no-untyped-def]
        yield conn

    pool = MagicMock()
    pool.acquire = _acquire
    monkeypatch.setattr(factory, "_pool", pool)
    await factory.probe_checkpointer()
    cur.execute.assert_awaited_once_with("SELECT 1")


@pytest.mark.asyncio
async def test_probe_checkpointer_without_pool_raises() -> None:
    import app.checkpointer.factory as factory

    factory._pool = None  # noqa: SLF001
    with pytest.raises(RuntimeError):
        await factory.probe_checkpointer()


def test_factory_uses_namespaced_saver():
    from app.checkpointer import factory
    from app.checkpointer.mysql import LangGraphMySQLSaver
    assert factory.AIOMySQLSaver is LangGraphMySQLSaver


async def test_schema_validation_failure_closes_pool(monkeypatch):
    from unittest.mock import AsyncMock

    from app.checkpointer import factory
    pool = _FakePool()
    monkeypatch.setattr(factory, "get_settings", _pool_settings)
    monkeypatch.setattr(factory.aiomysql, "create_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(factory, "AIOMySQLSaver", _FakeSaver)
    monkeypatch.setattr(_FakeSaver, "setup", AsyncMock(side_effect=RuntimeError("missing schema")))
    with pytest.raises(RuntimeError, match="missing schema"):
        await factory.init_checkpointer()
    assert pool.closed and pool.wait_closed_called
    assert not factory.has_checkpointer_pool()
