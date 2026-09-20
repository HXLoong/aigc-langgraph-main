"""HTTP tape exercises use local transports only; no models or external services."""
import asyncio
import importlib.util
import json
import stat

import httpx
import pytest


async def test_tape_preserves_actual_response_and_excludes_credentials(tmp_path):
    assert importlib.util.find_spec("harness.http_tape") is not None
    from harness.http_tape import RecordingTransport, ReplayTransport

    path = tmp_path / "private.jsonl"
    payload = b'{"code":42,"data":"actual rejection"}'

    async def upstream(request):
        assert request.headers["clientsecret"] == "client-secret-value"
        return httpx.Response(422, content=payload, headers={
            "content-type": "application/json", "set-cookie": "secret-cookie-value",
        })

    async with httpx.AsyncClient(transport=RecordingTransport(path, httpx.MockTransport(upstream))) as client:
        response = await client.post(
            "http://user:url-password@localhost:48080/order?token=query-secret-value&orderId=7",
            headers={"clientsecret": "client-secret-value", "signature": "signature-value"},
            json={"messageId": 12, "password": "body-password-value"},
        )
        assert response.status_code == 422 and response.content == payload
        assert response.headers["set-cookie"] == "secret-cookie-value"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text()
    for credential in ("url-password", "query-secret-value", "client-secret-value",
                       "signature-value", "body-password-value", "secret-cookie-value"):
        assert credential not in text
    async with httpx.AsyncClient(transport=ReplayTransport(path)) as client:
        response = await client.post(
            "http://localhost:48080/order?token=new-secret&orderId=7",
            json={"messageId": 12, "password": "new-password"},
        )
        assert response.status_code == 422 and response.content == payload


async def test_parallel_duplicate_requests_replay_in_dispatch_order_and_misses_fail_closed(tmp_path):
    from harness.http_tape import RecordingTransport, ReplayTransport, TapeMissError

    first_started, second_finished = asyncio.Event(), asyncio.Event()
    count = 0

    async def upstream(request):
        nonlocal count
        count += 1
        if count == 1:
            first_started.set()
            await second_finished.wait()
            return httpx.Response(200, text="first")
        second_finished.set()
        return httpx.Response(503, text="second")

    path = tmp_path / "parallel.jsonl"
    async with httpx.AsyncClient(transport=RecordingTransport(path, httpx.MockTransport(upstream))) as client:
        first = asyncio.create_task(client.get("http://localhost/order"))
        await first_started.wait()
        second = await client.get("http://localhost/order")
        assert second.status_code == 503 and (await first).text == "first"
    async with httpx.AsyncClient(transport=ReplayTransport(path)) as client:
        results = await asyncio.gather(client.get("http://localhost/order"), client.get("http://localhost/order"))
        assert [(result.status_code, result.text) for result in results] == [(200, "first"), (503, "second")]
        with pytest.raises(TapeMissError):
            await client.get("http://localhost/order")
        with pytest.raises(TapeMissError):
            await client.get("http://localhost/not-recorded")
    assert count == 2


async def test_pool_and_direct_tool_adapters_share_tape_and_restore_modules(tmp_path, monkeypatch):
    from app import config, main
    from app.tools import goats_rfq
    from app.tools.message_client import SetIntentRequest
    from app.tools.swap_client import SwapClientHttpx
    from harness.http_tape import RecordingTransport, ReplayTransport
    from scripts.run_with_http_tape import injected_tool_clients

    settings = config.get_settings().model_copy(update={
        "otc_api_base_url": "http://localhost:48080", "goats_base_url": "http://localhost:4999",
        "goats_client_id": "client", "goats_client_secret": "private-secret",
        "goats_opt_agent_id": "agent", "dry_run_backend": False,
    })
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    original_factory, original_httpx = main.MessageClientHttpx, goats_rfq.httpx
    real_async_client = httpx.AsyncClient
    path = tmp_path / "tools.jsonl"
    requests = []

    async def upstream(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"code": 0, "errCode": {"code": 200}, "data": {"ok": True}})

    async def use_tools(transport):
        async with injected_tool_clients(transport, timeout=1):
            await SwapClientHttpx().get("H-1")
            for _ in range(2):
                await main.MessageClientHttpx().set_intent(SetIntentRequest(
                    conversationId="c", messageId="12", intent="confirm_order", productType=1,
                ))
            assert await goats_rfq.parse_rfq_instrument("询价") == {"ok": True}
            assert httpx.AsyncClient is real_async_client

    await use_tools(RecordingTransport(path, httpx.MockTransport(upstream)))
    await use_tools(ReplayTransport(path))
    assert len(requests) == 4
    assert main.MessageClientHttpx is original_factory and goats_rfq.httpx is original_httpx


async def test_transport_timeout_is_recorded_and_replayed_without_exception_secrets(tmp_path):
    from harness.http_tape import RecordingTransport, ReplayTransport

    def upstream(request):
        raise httpx.ReadTimeout("private-url-and-secret", request=request)

    path = tmp_path / "timeout.jsonl"
    async with httpx.AsyncClient(transport=RecordingTransport(path, httpx.MockTransport(upstream))) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.get("http://localhost/order")
    assert "private-url-and-secret" not in path.read_text()
    assert json.loads(path.read_text().splitlines()[1])["error"] == "ReadTimeout"
    async with httpx.AsyncClient(transport=ReplayTransport(path)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await client.get("http://localhost/order")


def test_replay_requires_disabling_cached_http_response_shortcut(tmp_path, monkeypatch):
    from app import config
    from scripts.run_with_http_tape import create_app

    settings = config.get_settings().model_copy(update={
        "otc_api_base_url": "http://localhost:48080", "dry_run_backend": False,
        "request_idempotency": True,
    })
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="REQUEST_IDEMPOTENCY"):
        create_app("replay", tmp_path / "unused.jsonl")
