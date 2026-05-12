"""client 层统一的不可达异常（D2.3 / Issue #73）。

把 httpx 的网络异常 + 5xx 收敛成单一类型，让节点 / render 层能区分：
- BackendUnreachableError → 上游网络问题，输出"系统暂时不可用"友好回复
- 其他 Exception → 一般故障，走通用 fallback
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx


class BackendUnreachableError(RuntimeError):
    """真后端不可达：timeout / 拒绝连接 / 5xx。

    使用约定：
    - 仅在 *Client 类的方法中抛出，节点函数不应直接 raise
    - 节点函数被 @safe_node 包住后，异常类型保留在 ErrorInfo.type
    - render 节点根据 ErrorInfo.type == "BackendUnreachableError" 切换文案
    """

    def __init__(self, target: str, reason: str) -> None:
        super().__init__(f"{target}: {reason}")
        self.target = target  # 上游标识：option / swap / ticker
        self.reason = reason  # timeout / connect_error / http_5xx


@asynccontextmanager
async def translate_httpx_errors(target: str) -> AsyncIterator[None]:
    """把 httpx 的 timeout / ConnectError / 5xx 翻译成 BackendUnreachableError。

    4xx **不**算不可达（业务拒绝 / 鉴权问题），按原异常继续向上抛。
    """
    try:
        yield
    except httpx.TimeoutException as exc:
        raise BackendUnreachableError(target, "timeout") from exc
    except httpx.ConnectError as exc:
        raise BackendUnreachableError(target, "connect_error") from exc
    except httpx.HTTPStatusError as exc:
        if 500 <= exc.response.status_code < 600:
            raise BackendUnreachableError(
                target, f"http_{exc.response.status_code}"
            ) from exc
        raise


__all__ = ["BackendUnreachableError", "translate_httpx_errors"]
