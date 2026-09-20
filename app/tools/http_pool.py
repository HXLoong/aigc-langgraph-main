"""业务后端 HTTP 连接池（ADR 0024 D3：HTTP 客户端提升为 lifespan 单例）。

- lifespan 启动时 `open_shared_http_client()`，关闭时 `close_shared_http_client()`
- 各 *ClientHttpx 通过 `acquire_http_client(timeout=..., transport=...)` 取连接：
  测试注入了 transport → 独占临时 client；未开池（脚本 / 探针 / 单测）→ 独占临时 client；
  否则复用共享池，调用方**不得**关闭它
- 超时按调用方自己的设置逐请求传入（`timeout=` 参数），不吃池默认值
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

_shared: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


def get_shared_http_client() -> httpx.AsyncClient | None:
    return _shared


async def open_shared_http_client(
    *,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
    max_connections: int = 100,
    max_keepalive_connections: int = 20,
) -> httpx.AsyncClient:
    """幂等：已开则原样返回。trust_env=False 与既有 Client 一致（内网直连，绕过系统代理）。"""
    global _shared
    async with _lock:
        if _shared is None or _shared.is_closed:
            kwargs: dict[str, Any] = {
                "timeout": timeout,
                "trust_env": False,
                "limits": httpx.Limits(
                    max_connections=max_connections,
                    max_keepalive_connections=max_keepalive_connections,
                ),
            }
            if transport is not None:
                kwargs["transport"] = transport
            _shared = httpx.AsyncClient(**kwargs)
        return _shared


async def close_shared_http_client() -> None:
    global _shared
    client, _shared = _shared, None
    if client is not None and not client.is_closed:
        await client.aclose()


@asynccontextmanager
async def acquire_http_client(
    *, timeout: float, transport: httpx.AsyncBaseTransport | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    async with asyncio.timeout(timeout):
        if transport is None and _shared is not None and not _shared.is_closed:
            yield _shared
            return
        kwargs: dict[str, Any] = {"timeout": timeout, "trust_env": False}
        if transport is not None:
            kwargs["transport"] = transport
        async with httpx.AsyncClient(**kwargs) as client:
            yield client


__all__ = [
    "acquire_http_client",
    "close_shared_http_client",
    "get_shared_http_client",
    "open_shared_http_client",
]
