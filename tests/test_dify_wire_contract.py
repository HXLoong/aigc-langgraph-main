"""Java's existing Dify payload works without changing the HTTP path."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app


class CaptureGraph:
    state: dict | None = None

    async def ainvoke(self, state, **kwargs):
        self.state = state
        return {**state, "reply_text": "UNCHANGED_BACKEND_REPLY", "trace": []}


@pytest.fixture
def wire_client(monkeypatch):
    monkeypatch.setattr(routes, "attach_request_trace", AsyncMock(return_value=SimpleNamespace(
        handler=None, langfuse_trace_id=None, url=None,
    )))
    with TestClient(app) as client:
        client.app.state.main_graph = CaptureGraph()
        yield client


def test_query_and_top_level_files_reach_real_input_adapter(wire_client):
    files = [{"type": "image", "transfer_method": "remote_url", "url": "https://example.invalid/a.png"}]
    response = wire_client.post("/v1/workflows/run", json={
        "inputs": {"message_id": "123", "room_id": "test-room"},
        "query": "图片中的订单", "files": files, "response_mode": "blocking", "user": "test-user",
    })
    assert response.status_code == 200
    state = wire_client.app.state.main_graph.state
    assert state["raw_text"] == "图片中的订单"
    assert state["input_files"] == files


def test_dify_success_fields_preserve_existing_consumers(wire_client):
    response = wire_client.post("/v1/workflows/run", json={
        "inputs": {"raw_content": "原文"}, "query": "不得覆盖原文", "user": "test-user",
        "conversation_id": "original-session",
    })
    body = response.json()
    assert body["answer"] == body["data"]["outputs"]["reply_text"] == "UNCHANGED_BACKEND_REPLY"
    assert body["conversation_id"] == body["conversationId"] == "original-session"
    assert body["event"] == "message"
    assert body["mode"] == "advanced-chat"
    assert body["id"] == body["message_id"]
    assert isinstance(body["created_at"], int)
    assert isinstance(body["metadata"], dict)
    assert "error" not in body and "code" not in body
    assert wire_client.app.state.main_graph.state["raw_text"] == "原文"


def test_conflicting_attachment_locations_are_rejected_before_graph(wire_client):
    response = wire_client.post("/v1/workflows/run", json={
        "inputs": {"files": [{"url": "first"}]}, "files": [{"url": "second"}], "user": "u",
    })
    assert response.status_code == 422
    assert wire_client.app.state.main_graph.state is None


def test_interface_errors_use_dify_envelope(wire_client):
    response = wire_client.post("/v1/workflows/run", json={
        "inputs": {}, "response_mode": "streaming", "user": "u",
    })
    assert response.status_code == 400
    assert response.json()["status"] == 400
    assert response.json()["code"] == "invalid_param"
    assert response.json()["message"]


def test_graph_crash_is_not_an_empty_success(wire_client):
    wire_client.app.state.main_graph.ainvoke = AsyncMock(side_effect=RuntimeError("private-detail"))
    response = wire_client.post("/v1/workflows/run", json={"inputs": {}, "user": "u"})
    assert response.status_code == 502
    assert response.json()["code"] == "internal_server_error"
    assert "private-detail" not in response.text
