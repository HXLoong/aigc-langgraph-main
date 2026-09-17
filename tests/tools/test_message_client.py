"""MessageClientHttpx 的线协议和有限重试契约。"""
from __future__ import annotations

import json
import traceback
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.tools.message_client import MessageClientHttpx, SetIntentError, SetIntentRequest


@pytest.fixture()
def request_body() -> SetIntentRequest:
    return SetIntentRequest(
        conversationId="(\\opaque-id\\\\)", messageId="42",
        intent="new_inquiry", productType=0,
    )


@pytest.mark.parametrize("failure", ["timeout", "connect", "500", "503", "599"])
async def test_transient_failure_retries_once_after_100ms(
    monkeypatch: pytest.MonkeyPatch, request_body: SetIntentRequest, failure: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("private details", request=request)
            if failure == "connect":
                raise httpx.ConnectError("private details", request=request)
            return httpx.Response(int(failure))
        return httpx.Response(200, json={"code": 0, "data": True})

    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)
    client = MessageClientHttpx(
        base_url="https://java.invalid", token="", transport=httpx.MockTransport(handler),
    )
    result = await client.set_intent(request_body)

    assert result["code"] == 0
    assert result["data"] is True
    assert len(requests) == 2
    assert requests[0].content == requests[1].content
    sleep.assert_awaited_once_with(0.1)


@pytest.mark.parametrize("body", [
    {}, {"code": None}, {"code": "0"}, {"code": False}, [], "private-invalid-json",
])
async def test_missing_or_invalid_success_code_fails_without_retry(
    monkeypatch: pytest.MonkeyPatch, request_body: SetIntentRequest, body: object,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if isinstance(body, str):
            return httpx.Response(200, text=body)
        return httpx.Response(200, json=body)

    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)
    client = MessageClientHttpx(
        base_url="https://java.invalid", token="", transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SetIntentError, match="^set-intent: invalid_response$"):
        await client.set_intent(request_body)
    assert len(requests) == 1
    sleep.assert_not_awaited()


async def test_set_intent_uses_java_wire_contract_and_auth_even_in_dry_run(
    monkeypatch: pytest.MonkeyPatch, request_body: SetIntentRequest,
) -> None:
    settings = get_settings().model_copy(update={
        "otc_api_base_url": "https://java.invalid/",
        "otc_api_secret": "test-token",
        "goats_client_id": "test-client",
        "goats_client_secret": "test-secret",
        "goats_extapp_salt": "test-salt",
        "dry_run_backend": True,
    })
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.tools.auth.time.time", lambda: 1700000000.0)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": True})

    result = await MessageClientHttpx(transport=httpx.MockTransport(handler)).set_intent(
        request_body,
    )
    assert result["code"] == 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://java.invalid/admin-api/openapi/xbot/message/set-intent"
    assert json.loads(request.content) == {
        "conversationId": "(\\opaque-id\\\\)", "messageId": "42",
        "intent": "new_inquiry", "productType": 0, "orderIds": [],
    }
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["x-goats-clientid"] == "test-client"
    assert request.headers["x-goats-timestamp"] == "1700000000000"
    assert request.headers["x-goats-signature"] == (
        "408b83cbcde50df6e109460a0a5ca9f1058820b23590858e5995e625ff451e49"
    )


@pytest.mark.parametrize("failure,attempts,reason", [
    ("timeout", 2, "timeout"), ("connect", 2, "connect_error"),
    ("503", 2, "http_503"), ("400", 1, "http_400"), ("401", 1, "http_401"),
    ("429", 1, "http_429"), ("302", 1, "http_302"),
    ("business", 1, "business_error"), ("read", 1, "transport_error"),
])
async def test_final_failure_has_bounded_attempts_and_sanitized_error(
    monkeypatch: pytest.MonkeyPatch, request_body: SetIntentRequest,
    failure: str, attempts: int, reason: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive-message", request=request)
        if failure == "connect":
            raise httpx.ConnectError("sensitive-message", request=request)
        if failure == "read":
            raise httpx.ReadError("sensitive-message", request=request)
        if failure == "business":
            return httpx.Response(200, json={"code": 987, "msg": "sensitive-message"})
        return httpx.Response(int(failure), text="sensitive-message")

    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)
    client = MessageClientHttpx(
        base_url="https://private-host.invalid", token="private-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SetIntentError, match=f"^set-intent: {reason}$") as caught:
        await client.set_intent(request_body)
    assert len(requests) == attempts
    assert sleep.await_count == attempts - 1
    formatted = "".join(traceback.format_exception(caught.value))
    assert "sensitive-message" not in formatted
    assert "private-host.invalid" not in formatted
    assert "private-token" not in formatted


@pytest.mark.parametrize("overrides", [
    {"messageId": 42}, {"conversationId": 42}, {"productType": 2}, {"orderIds": ["order-1"]},
])
def test_request_rejects_invalid_wire_types_and_nonempty_orders(
    request_body: SetIntentRequest, overrides: dict,
) -> None:
    with pytest.raises(ValidationError):
        SetIntentRequest.model_validate({**request_body.model_dump(), **overrides})
