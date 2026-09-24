"""不可达异常 + translate_httpx_errors context manager 测试。"""
from __future__ import annotations

import httpx
import pytest

from app.tools.exceptions import BackendUnreachableError, translate_httpx_errors


@pytest.mark.asyncio
async def test_translate_timeout() -> None:
    with pytest.raises(BackendUnreachableError) as exc_info:
        async with translate_httpx_errors("option"):
            raise httpx.TimeoutException("upstream slow")
    assert exc_info.value.target == "option"
    assert exc_info.value.reason == "timeout"


@pytest.mark.asyncio
async def test_translate_connect_error() -> None:
    with pytest.raises(BackendUnreachableError) as exc_info:
        async with translate_httpx_errors("swap"):
            raise httpx.ConnectError("unreachable")
    assert exc_info.value.target == "swap"
    assert exc_info.value.reason == "connect_error"


@pytest.mark.asyncio
async def test_translate_5xx() -> None:
    fake_resp = httpx.Response(503, content=b"")
    with pytest.raises(BackendUnreachableError) as exc_info:
        async with translate_httpx_errors("ticker"):
            raise httpx.HTTPStatusError(
                "server error", request=httpx.Request("GET", "http://x"), response=fake_resp
            )
    assert exc_info.value.target == "ticker"
    assert exc_info.value.reason == "http_503"


@pytest.mark.asyncio
async def test_translate_4xx_passes_through() -> None:
    """4xx 不算不可达，原异常继续向上抛（业务侧处理）。"""
    fake_resp = httpx.Response(400, content=b"")
    with pytest.raises(httpx.HTTPStatusError):
        async with translate_httpx_errors("option"):
            raise httpx.HTTPStatusError(
                "bad request", request=httpx.Request("POST", "http://x"), response=fake_resp
            )


@pytest.mark.asyncio
async def test_translate_other_exception_passes_through() -> None:
    """非 httpx 异常原样抛出，不被翻译。"""
    with pytest.raises(ValueError, match="nope"):
        async with translate_httpx_errors("swap"):
            raise ValueError("nope")


@pytest.mark.asyncio
async def test_translate_ok_path_no_op() -> None:
    """正常路径 context manager 不影响业务结果。"""
    async with translate_httpx_errors("option"):
        result = 42
    assert result == 42


def test_unreachable_error_str_contains_target_reason() -> None:
    exc = BackendUnreachableError("ticker", "timeout")
    assert "ticker" in str(exc)
    assert "timeout" in str(exc)
