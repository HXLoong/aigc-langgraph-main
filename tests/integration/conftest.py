"""集成测试公共 fixture · 让 client 调 mock_api（内存调用，无端口）。

设计意图：
  - 解决"既不在真实环境也不基于 Mock API"的盲区：业务 client
    （OptionClientHttpx / SwapClientHttpx / TickerClientHttpx）原本只
    能调真后端；现在通过 transport 注入把 client 切到 mock_api FastAPI
    实例的内存调用上跑（httpx.ASGITransport）。
  - 单元测试不依赖此 fixture；只有 tests/integration/ 下的集成测试用。
  - 真后端 probe（scripts/probe_*.py）也不依赖此 fixture（继续直连）。

参考：mock_api/test_backend_api.py（已用 ASGITransport 跑过 10 端点）。
"""
from __future__ import annotations

import httpx
import pytest

from mock_api.server import app as mock_app


@pytest.fixture
def mock_api_transport() -> httpx.ASGITransport:
    """共享一个 mock_api ASGI transport（无端口、零启动开销）。"""
    return httpx.ASGITransport(app=mock_app)


@pytest.fixture
def option_client(mock_api_transport: httpx.ASGITransport):
    """OptionClient 走 mock_api。base_url 用 'http://mock' 占位（transport 拦截）。"""
    from app.tools.option_client import OptionClientHttpx

    return OptionClientHttpx(
        base_url="http://mock",
        token="test-token",
        transport=mock_api_transport,
    )


@pytest.fixture
def swap_client(mock_api_transport: httpx.ASGITransport):
    from app.tools.swap_client import SwapClientHttpx

    return SwapClientHttpx(
        base_url="http://mock",
        token="test-token",
        transport=mock_api_transport,
    )


@pytest.fixture
def ticker_client(mock_api_transport: httpx.ASGITransport):
    from app.tools.ticker_client import TickerClientHttpx

    return TickerClientHttpx(
        base_url="http://mock",
        token="test-token",
        transport=mock_api_transport,
    )


@pytest.fixture
def goats_agent_client(mock_api_transport: httpx.ASGITransport):
    """GoatsAgentClient 走 mock_api（mock 双前缀挂载，base 不带 /api 也可达）。"""
    from app.tools.goats_agent_client import GoatsAgentClientHttpx

    return GoatsAgentClientHttpx(
        base_url="http://mock",
        client_id="mock-client-id",
        client_secret="mock-client-secret",
        extapp_salt="mock-salt",
        transport=mock_api_transport,
    )
