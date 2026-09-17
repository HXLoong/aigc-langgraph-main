"""HTTP 客户端 lifespan 单例（ADR 0024 D3）：三个业务 Client 复用一个连接池，测试期 transport 注入优先。"""
from __future__ import annotations

import httpx
import pytest

from app.tools import http_pool
from app.tools.swap_client import SwapClientHttpx


@pytest.fixture(autouse=True)
async def _clean_pool():
    await http_pool.close_shared_http_client()
    yield
    await http_pool.close_shared_http_client()


@pytest.mark.asyncio
async def test_without_pool_each_acquire_owns_and_closes_a_client() -> None:
    assert http_pool.get_shared_http_client() is None
    async with http_pool.acquire_http_client(timeout=1.0) as client:
        assert isinstance(client, httpx.AsyncClient)
    assert client.is_closed


@pytest.mark.asyncio
async def test_pool_is_reused_and_not_closed_by_callers() -> None:
    shared = await http_pool.open_shared_http_client(timeout=5.0)
    async with http_pool.acquire_http_client(timeout=1.0) as a:
        pass
    async with http_pool.acquire_http_client(timeout=1.0) as b:
        pass
    assert a is shared and b is shared and not shared.is_closed
    await http_pool.close_shared_http_client()
    assert shared.is_closed and http_pool.get_shared_http_client() is None


@pytest.mark.asyncio
async def test_transport_injection_bypasses_pool() -> None:
    shared = await http_pool.open_shared_http_client(timeout=5.0)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    async with http_pool.acquire_http_client(timeout=1.0, transport=transport) as client:
        assert client is not shared
    assert client.is_closed and not shared.is_closed


@pytest.mark.asyncio
async def test_business_client_goes_through_pool_with_its_own_timeout() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": {"orderId": "H-1"}})

    await http_pool.open_shared_http_client(timeout=5.0, transport=httpx.MockTransport(handler))
    result = await SwapClientHttpx(base_url="http://swap.test", token="t", timeout=2.5).get("H-1")
    assert result.code == 0
    assert seen and seen[0].url.host == "swap.test"
    assert seen[0].extensions["timeout"]["read"] == 2.5, "每个 Client 的超时按自己的设置，不吃池默认值"
    assert not http_pool.get_shared_http_client().is_closed


def test_lifespan_opens_and_closes_pool() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app):
        shared = http_pool.get_shared_http_client()
        assert shared is not None and not shared.is_closed
    assert http_pool.get_shared_http_client() is None
