"""Caught graph errors must remain visible in Langfuse and the HTTP diagnostics."""
from unittest.mock import MagicMock
from uuid import uuid4

from app.api.routes import _state_to_outputs
from app.graph.safe_node import safe_node
from app.graph.state import ErrorInfo, TraceEntry
from app.observability import tracing
from app.tools.exceptions import BackendUnreachableError


def test_http_diagnostic_identifies_failed_node_and_elapsed_time():
    output = _state_to_outputs({"error": ErrorInfo(node="swap_place_order_submit", type="BackendUnreachableError", message="swap: timeout"),
        "trace": [TraceEntry(node="swap_place_order_submit", elapsed_ms=5002, decision="error")]})
    detail = output["diagnostic"]
    assert detail["code"] == "E4" and detail["node"] == "swap_place_order_submit"
    assert detail["elapsed_ms"] == 5002
    assert "超时" in detail["summary"]


async def test_caught_node_error_marks_current_observation(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(tracing, "_enabled", lambda: True)
    monkeypatch.setattr(tracing, "_ensure_client", lambda: client)
    @safe_node
    async def submit(state):
        raise BackendUnreachableError("swap", "timeout")
    result = await submit({})
    assert result["error"].code == "E4"
    assert client.update_current_span.call_args.kwargs["level"] == "ERROR"
    assert "submit" in client.update_current_span.call_args.kwargs["status_message"]


def test_parent_callback_marks_failed_graph_and_keeps_error_details_private(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(tracing, "_enabled", lambda: True)
    monkeypatch.setattr(tracing, "_ensure_client", lambda: client)
    callback = tracing.HandledErrorCallback()
    callback.on_chain_end({"error": ErrorInfo(node="extract", type="ValidationError", message="private-value")}, run_id=uuid4())
    kwargs = client.update_current_span.call_args.kwargs
    assert kwargs["level"] == "ERROR"
    assert "private-value" not in str(kwargs)


async def test_telemetry_failure_does_not_hide_original_error(monkeypatch):
    client = MagicMock()
    client.update_current_span.side_effect = RuntimeError("telemetry unavailable")
    monkeypatch.setattr(tracing, "_enabled", lambda: True)
    monkeypatch.setattr(tracing, "_ensure_client", lambda: client)
    @safe_node
    async def submit(state):
        raise BackendUnreachableError("swap", "timeout")
    assert (await submit({}))["error"].type == "BackendUnreachableError"


def test_callback_updates_the_matching_run_instead_of_an_ended_child(monkeypatch):
    monkeypatch.setattr(tracing, "_enabled", lambda: True)
    run_id = uuid4()
    root = MagicMock()
    handler = MagicMock()
    handler._runs = {run_id: root}
    callback = tracing.HandledErrorCallback(handler)
    callback.on_chain_end({"error": ErrorInfo(node="submit", type="BackendUnreachableError", message="swap: timeout")}, run_id=run_id)
    assert root.update.call_args.kwargs["level"] == "ERROR"
