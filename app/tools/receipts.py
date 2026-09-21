"""Java 回执校验与 Dify 展示投影；原始业务结果保留在 api_result。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.tools.exceptions import BackendUnreachableError, EmptyBackendResultError

SERVICE_UNAVAILABLE = "交易指令服务暂不可用"
UNCERTAIN_REPLY = "交易指令执行结果待核对，请勿重复提交，请联系交易员或运营核查。"


@asynccontextmanager
async def receipt_guard(target: str) -> AsyncIterator[None]:
    """Only wrap dispatch/decoding; DTO errors before dispatch are not uncertain writes."""
    try:
        yield
    except (httpx.HTTPError, ValueError) as exc:
        raise BackendUnreachableError(target, f"unverifiable_receipt:{type(exc).__name__}") from exc


def receipt_update(result: Any, target: str) -> dict[str, Any]:
    """调用后无法验证回执时保留不确定状态，不推断写入成功或失败。"""
    code = result.get("code") if isinstance(result, dict) else None
    if not isinstance(code, int) or isinstance(code, bool):
        raise EmptyBackendResultError(target, None)
    value = result.get("data") if code == 0 else result.get("msg")
    if code == 0 and (not isinstance(value, str) or not value.strip()):
        raise EmptyBackendResultError(target, code)
    return {"api_code": code, "api_result": value}


def receipt_text(code: Any, value: Any) -> str:
    if code == 500:
        return SERVICE_UNAVAILABLE
    if code not in (0, None) and not value:
        return "未知错误"
    return str(value) if value is not None else ""
