"""结构化日志（ADR 0024 D5）：structlog 接管 stdlib logging，trace_id 经 contextvars 进每条日志。"""
from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from app.observability import logs


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    structlog.contextvars.clear_contextvars()
    logs.configure_logging(level="INFO", fmt="console")


def _capture(level: str = "INFO", fmt: str = "json") -> io.StringIO:
    stream = io.StringIO()
    logs.configure_logging(level=level, fmt=fmt, stream=stream)
    return stream


def test_stdlib_logger_emits_json_with_bound_trace_id() -> None:
    stream = _capture()
    with logs.bound_request_context(trace_id="t-1", conversation_id="c-1", message_id=42):
        logging.getLogger("app.subgraphs.swap.confirm").info("node=%s done", "swap_confirm")
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["event"] == "node=swap_confirm done"
    assert record["level"] == "info" and record["logger"] == "app.subgraphs.swap.confirm"
    assert (record["trace_id"], record["conversation_id"], record["message_id"]) == ("t-1", "c-1", 42)
    assert "timestamp" in record


def test_context_is_cleared_after_request() -> None:
    stream = _capture()
    with logs.bound_request_context(trace_id="t-1"):
        pass
    logging.getLogger("app.x").warning("after")
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert "trace_id" not in record


def test_level_from_settings_is_respected() -> None:
    stream = _capture(level="WARNING")
    logging.getLogger("app.x").info("hidden")
    logging.getLogger("app.x").warning("shown")
    lines = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
    assert [r["event"] for r in lines] == ["shown"]


def test_console_format_is_human_readable() -> None:
    stream = _capture(fmt="console")
    logging.getLogger("app.x").info("hello console")
    text = stream.getvalue()
    assert "hello console" in text
    with pytest.raises(ValueError):
        json.loads(text.strip())


def test_auto_format_picks_json_outside_development() -> None:
    from app.config import get_settings

    dev = get_settings().model_copy(update={"environment": "development", "log_format": "auto", "log_level": "DEBUG"})
    prod = get_settings().model_copy(update={"environment": "production", "log_format": "auto"})
    assert logs.resolve_format(dev) == "console"
    assert logs.resolve_format(prod) == "json"
    assert logs.resolve_format(prod.model_copy(update={"log_format": "console"})) == "console"


def test_route_binds_trace_context_for_the_whole_graph_run() -> None:
    """/v1/workflows/run 期间图内任何一条日志都带 trace_id / conversation_id / message_id。"""
    from fastapi.testclient import TestClient

    from app.main import app

    seen: dict = {}

    class _Graph:
        async def ainvoke(self, state, config, **kwargs):  # type: ignore[no-untyped-def]
            seen.update(structlog.contextvars.get_contextvars())
            return {**state, "reply_text": "ok", "tickers": [], "trace": []}

    with TestClient(app) as client:
        client.app.state.main_graph = _Graph()
        r = client.post("/v1/workflows/run", json={
            "conversation_id": "conv-log", "user": "u1", "response_mode": "blocking",
            "inputs": {"rawContent": "hi", "messageId": 77, "roomId": "r1", "userId": "u1"},
        })
    assert r.status_code == 200
    assert seen["trace_id"] == r.json()["data"]["outputs"]["trace_id"]
    assert seen["conversation_id"] == "conv-log" and seen["message_id"] == 77
    assert "trace_id" not in structlog.contextvars.get_contextvars(), "请求结束后清空"
