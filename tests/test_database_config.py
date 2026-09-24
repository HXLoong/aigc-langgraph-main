"""一个 MYSQL_URI 连接配置驱动 checkpoint、审计和请求幂等。"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.config import Settings

URI = "mysql+aiomysql://user:pass@localhost:3308/shared_java"


def _isolate_settings(monkeypatch):
    for key in ("MYSQL_URI", "CHECKPOINT_MYSQL_URI", "BUSINESS_MYSQL_URI"):
        monkeypatch.delenv(key, raising=False)
    return {
        "_env_file": None,
        "qwen_api_base": "http://localhost:9999/v1",
        "qwen_api_key": "test-key",
        "otc_api_base_url": "http://localhost:48080",
        "otc_api_secret": "test-secret",
    }


def test_single_mysql_environment_variable_is_sufficient(monkeypatch):
    kwargs = _isolate_settings(monkeypatch)
    monkeypatch.setenv("MYSQL_URI", URI)
    settings = Settings(**kwargs)
    assert settings.mysql_uri == URI


def test_legacy_connections_cannot_replace_required_mysql_uri(monkeypatch):
    kwargs = _isolate_settings(monkeypatch)
    monkeypatch.setenv("CHECKPOINT_MYSQL_URI", URI)
    monkeypatch.setenv("BUSINESS_MYSQL_URI", URI)
    with pytest.raises(ValidationError) as exc:
        Settings(**kwargs)
    assert {error["loc"] for error in exc.value.errors()} == {("mysql_uri",)}


async def test_persist_connects_using_single_mysql_uri(monkeypatch):
    import aiomysql

    from app.storage.node_trace import write_node_trace

    monkeypatch.setattr("app.storage.node_trace.get_settings", lambda: SimpleNamespace(
        mysql_uri=URI, persist_timeout_seconds=5,
    ))
    cursor = MagicMock(executemany=AsyncMock())

    @asynccontextmanager
    async def cursor_context():
        yield cursor

    connection = MagicMock(cursor=cursor_context)
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(aiomysql, "connect", connect)
    await write_node_trace([{"node": "render"}], "message", "conversation")
    assert connect.call_args.kwargs["db"] == "shared_java"
    assert connect.call_args.kwargs["port"] == 3308
    assert "INSERT INTO langgraph_node_trace" in cursor.executemany.call_args.args[0]
    connection.close.assert_called_once()


async def test_lifespan_wires_idempotency_using_single_mysql_uri(monkeypatch):
    import app.main as app_main

    monkeypatch.setattr(app_main, "get_settings", lambda: SimpleNamespace(
        mysql_uri=URI, request_idempotency=True, use_mysql_checkpointer=False,
        environment="development", backend_timeout_seconds=60, persist_timeout_seconds=5,
        log_level="INFO", log_format="console",
    ))
    async with app_main.lifespan(app_main.app):
        store = app_main.app.state.idempotency_store
        args = store._conn_args
        assert (args["host"], args["port"], args["user"], args["password"], args["db"]) == (
            "localhost", 3308, "user", "pass", "shared_java",
        )


def test_instrument_lookup_settings_are_gone(monkeypatch):
    """ADR 0025：标的识别归 Java，不存在标的池直连与 securities-instrument 配置。"""
    kwargs = _isolate_settings(monkeypatch)
    monkeypatch.setenv("MYSQL_URI", URI)
    settings = Settings(**kwargs)
    leftovers = sorted(
        name for name in type(settings).model_fields
        if name.startswith("ticker_mysql_") or name.startswith("securities_instrument_")
    )
    assert leftovers == []
