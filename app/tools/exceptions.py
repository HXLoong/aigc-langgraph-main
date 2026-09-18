"""client/业务后端调用层的统一异常。

让节点 / render 层能够区分：
- BackendUnreachableError → 上游网络问题，输出"系统暂时不可用"友好回复
- MissingBackendContextError → 调用必需上下文缺失，不得静默跳过后端
- EmptyBackendResultError → 后端没有返回可展示的业务结果
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


class MissingBackendContextError(RuntimeError):
    """调用业务后端所需的机器人上下文字段缺失。"""

    def __init__(self, target: str, missing_fields: list[str]) -> None:
        self.target = target
        self.missing_fields = tuple(missing_fields)
        fields = ", ".join(self.missing_fields)
        super().__init__(f"{target}: missing required context fields: {fields}")


class EmptyBackendResultError(RuntimeError):
    """业务后端返回成功或失败状态，但没有可供用户展示的结果。"""

    def __init__(self, target: str, code: int) -> None:
        self.target = target
        self.code = code
        super().__init__(f"{target}: backend returned an empty result (code={code})")


@asynccontextmanager
async def translate_httpx_errors(target: str) -> AsyncIterator[None]:
    """把 httpx 的 timeout / ConnectError / 5xx 翻译成 BackendUnreachableError。

    4xx **不**算不可达（业务拒绝 / 鉴权问题），按原异常继续向上抛。
    """
    try:
        yield
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise BackendUnreachableError(target, "timeout") from exc
    except httpx.ConnectError as exc:
        raise BackendUnreachableError(target, "connect_error") from exc
    except httpx.HTTPStatusError as exc:
        if 500 <= exc.response.status_code < 600:
            raise BackendUnreachableError(
                target, f"http_{exc.response.status_code}"
            ) from exc
        raise


__all__ = [
    "BackendUnreachableError",
    "EmptyBackendResultError",
    "MissingBackendContextError",
    "translate_httpx_errors",
]
