"""D2.3 client 不可达场景集成测试（Issue #73）。

3 个 client × 4 类故障 = 12 个测试。
用 httpx.MockTransport 模拟 timeout / ConnectError / 5xx / 4xx。
"""
from __future__ import annotations

import httpx
import pytest

from app.tools import (
    FinancialOrderOpenApiBaseSaveReqVO,
    FinancialOrderOpenApiSaveReqVO,
    OptionIntentionType,
    SecuritiesInstrumentReqVO,
    SwapIntentionType,
    SwapOrderOpenApiBaseSaveReqVO,
    SwapOrderOpenApiSaveReqVO,
)
from app.tools.exceptions import BackendUnreachableError
from app.tools.option_client import OptionClientHttpx
from app.tools.swap_client import SwapClientHttpx
from app.tools.ticker_client import KeywordItem, TickerClientHttpx

# ============================================================
# httpx MockTransport 工厂
# ============================================================


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """把 httpx.AsyncClient 的构造行为替换：所有请求走 handler。"""
    real_init = httpx.AsyncClient.__init__

    def _patched_init(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _patched_init)


def _timeout_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.TimeoutException("simulated timeout", request=request)


def _connect_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("simulated connect refused", request=request)


def _500_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, json={"code": 0, "msg": "internal", "data": None})


def _400_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(400, json={"code": 400, "msg": "bad params", "data": None})


# ============================================================
# fixtures: 3 个 client + 1 个简单请求 model
# ============================================================


@pytest.fixture
def option_client() -> OptionClientHttpx:
    return OptionClientHttpx(base_url="http://example.invalid", timeout=2.0, token="t")


@pytest.fixture
def swap_client() -> SwapClientHttpx:
    return SwapClientHttpx(base_url="http://example.invalid", timeout=2.0, token="t")


@pytest.fixture
def ticker_client() -> TickerClientHttpx:
    return TickerClientHttpx(base_url="http://example.invalid", timeout=2.0, token="t")


def _option_req() -> FinancialOrderOpenApiSaveReqVO:
    return FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType.NEW_INQUIRY,
        conversationId="c1",
        messageId=1,
        messageContent="ping",
        rawContent="ping",
        userId="u1",
        roomId="r1",
        orderList=[FinancialOrderOpenApiBaseSaveReqVO()],
    )


def _swap_req() -> SwapOrderOpenApiSaveReqVO:
    return SwapOrderOpenApiSaveReqVO(
        type=SwapIntentionType.PLACE_ORDER_REQUEST,
        conversationId="c1",
        messageId=1,
        messageContent="ping",
        rawContent="ping",
        userId="u1",
        roomId="r1",
        orderList=[SwapOrderOpenApiBaseSaveReqVO()],
    )


def _ticker_req() -> SecuritiesInstrumentReqVO:
    return SecuritiesInstrumentReqVO(
        keywordItems=[KeywordItem(keyword="贵州茅台", isFull=False)]
    )


# ============================================================
# 12 个故障矩阵
# ============================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler,expected_reason",
    [
        (_timeout_handler, "timeout"),
        (_connect_handler, "connect_error"),
        (_500_handler, "http_503"),
    ],
)
async def test_option_operate_unreachable(
    option_client: OptionClientHttpx,
    monkeypatch: pytest.MonkeyPatch,
    handler,
    expected_reason: str,
) -> None:
    _patch_async_client(monkeypatch, handler)
    with pytest.raises(BackendUnreachableError) as exc_info:
        await option_client.operate(_option_req())
    assert exc_info.value.target == "option"
    assert exc_info.value.reason == expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler,expected_reason",
    [
        (_timeout_handler, "timeout"),
        (_connect_handler, "connect_error"),
        (_500_handler, "http_503"),
    ],
)
async def test_swap_operate_unreachable(
    swap_client: SwapClientHttpx,
    monkeypatch: pytest.MonkeyPatch,
    handler,
    expected_reason: str,
) -> None:
    _patch_async_client(monkeypatch, handler)
    with pytest.raises(BackendUnreachableError) as exc_info:
        await swap_client.operate(_swap_req())
    assert exc_info.value.target == "swap"
    assert exc_info.value.reason == expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler,expected_reason",
    [
        (_timeout_handler, "timeout"),
        (_connect_handler, "connect_error"),
        (_500_handler, "http_503"),
    ],
)
async def test_ticker_search_unreachable(
    ticker_client: TickerClientHttpx,
    monkeypatch: pytest.MonkeyPatch,
    handler,
    expected_reason: str,
) -> None:
    _patch_async_client(monkeypatch, handler)
    with pytest.raises(BackendUnreachableError) as exc_info:
        await ticker_client.search_securities_instrument(_ticker_req())
    assert exc_info.value.target == "ticker"
    assert exc_info.value.reason == expected_reason


# ============================================================
# 4xx 仍然走原异常，不转 BackendUnreachableError
# ============================================================


@pytest.mark.asyncio
async def test_option_operate_4xx_not_unreachable(
    option_client: OptionClientHttpx,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_async_client(monkeypatch, _400_handler)
    with pytest.raises(httpx.HTTPStatusError):
        await option_client.operate(_option_req())


@pytest.mark.asyncio
async def test_swap_operate_4xx_not_unreachable(
    swap_client: SwapClientHttpx,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_async_client(monkeypatch, _400_handler)
    with pytest.raises(httpx.HTTPStatusError):
        await swap_client.operate(_swap_req())


@pytest.mark.asyncio
async def test_ticker_search_4xx_not_unreachable(
    ticker_client: TickerClientHttpx,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_async_client(monkeypatch, _400_handler)
    with pytest.raises(httpx.HTTPStatusError):
        await ticker_client.search_securities_instrument(_ticker_req())
