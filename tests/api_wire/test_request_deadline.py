"""Deadline cancels work and its HTTP response is safe to replay."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.api.idempotency import InMemoryIdempotencyStore
from app.config import get_settings
from app.main import app


def test_deadline_cancels_graph_and_duplicate_never_reexecutes(monkeypatch):
    settings = get_settings().model_copy(update={
        "request_timeout_seconds": .12, "response_reserve_seconds": .04,
    })
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    cancelled = []

    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(.3)
            return {"reply_text": "too late"}
        finally:
            cancelled.append(True)

    with TestClient(app) as client:
        graph = AsyncMock()
        graph.ainvoke.side_effect = slow
        client.app.state.main_graph = graph
        client.app.state.idempotency_store = InMemoryIdempotencyStore()
        body = {"inputs": {"rawContent": "确认下单", "messageId": 700, "roomId": "r"}, "user": "u"}
        first = client.post("/v1/workflows/run", json=body)
        second = client.post("/v1/workflows/run", json=body)
        assert first.status_code == second.status_code == 504
        assert first.json() == second.json()
        assert first.json()["code"] == "workflow_timeout"
        assert cancelled == [True]
        assert graph.ainvoke.await_count == 1
        client.app.state.idempotency_store = None


@pytest.mark.parametrize("factory", ["get_qwen_standard", "get_qwen_thinking", "get_qwen_structured", "get_qwen_complex", "get_qwen_vl", "make_qwen_thinking"])
def test_graph_is_the_only_owner_of_llm_retries(factory):
    from app.llm import clients
    function = getattr(clients, factory)
    if hasattr(function, "cache_clear"):
        function.cache_clear()
    assert function().max_retries == 0


def test_default_budgets_leave_time_before_java_timeout():
    from app.config import Settings
    fields = Settings.model_fields
    assert fields["llm_timeout_seconds"].default == 20
    assert fields["backend_timeout_seconds"].default == 5
    assert fields["request_timeout_seconds"].default == 60


async def test_tool_budget_is_wall_clock_not_just_socket_timeout():
    import httpx

    from app.tools.http_pool import acquire_http_client

    cancelled = []
    async def slow(request):
        try:
            await asyncio.sleep(.2)
            return httpx.Response(200, json={})
        finally:
            cancelled.append(True)

    with pytest.raises(TimeoutError):
        async with acquire_http_client(timeout=.01, transport=httpx.MockTransport(slow)) as client:
            await client.get("http://test.invalid")
    assert cancelled == [True]


async def test_llm_budget_is_wall_clock_and_cancels_provider(monkeypatch):
    from langchain_openai import ChatOpenAI

    from app.llm.clients import _ChatLLM

    cancelled = []
    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(.2)
        finally:
            cancelled.append(True)
    monkeypatch.setattr(ChatOpenAI, "ainvoke", slow)
    model = _ChatLLM(model="test", api_key="test-only", timeout=.01, max_retries=0)
    with pytest.raises(TimeoutError):
        await model.ainvoke("private input")
    assert cancelled == [True]


@pytest.mark.parametrize("field", ["multimodal_fetch_timeout_seconds", "goats_agent_rfq_timeout_seconds", "goats_agent_instruction_timeout_seconds"])
def test_all_tool_default_budgets_are_five_seconds(field):
    from app.config import Settings
    assert Settings.model_fields[field].default == 5
