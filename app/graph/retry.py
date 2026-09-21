"""只读 IO 节点的 RetryPolicy 与重试耗尽兜底（ADR 0024 D3）。

分工：
- `@io_node`：@safe_node 的只读 IO 变体——**可重试异常**（网络不可达 / LLM 限流超时）穿透
  到 LangGraph 的 RetryPolicy；其它异常与 @safe_node 一样就地落 `state['error']`
- `add_io_node(g, name, fn)`：注册时挂 RetryPolicy + 节点级 error_handler，重试耗尽后由
  `retry_exhausted_handler` 把异常写成 ErrorInfo，图不崩、cascade 照常走 fallback
- 写类节点（下单 / 撤单 / 确认 / 平仓）**绝不**用本模块：超时后自动重试可能重复下单，
  它们保持 @safe_node，超时直接交 render 出"系统暂时不可用"

SDK 层（langchain_openai max_retries、httpx）的重试对图不可见；图级重试每次都打
`otc_agent_node_total{status="retry"}` 并写日志，可观测才是这层的价值。
"""
from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import openai
from langchain_core.exceptions import OutputParserException
from langgraph.errors import NodeError
from langgraph.graph import StateGraph
from langgraph.types import RetryPolicy
from pydantic import ValidationError

from app.config import get_settings
from app.extraction.fields import EvidenceError
from app.graph.safe_node import NodeFn, P, safe_node
from app.graph.state import ErrorInfo, TraceEntry
from app.observability.metrics import emit_node_completed
from app.tools.exceptions import BackendUnreachableError

#: 只读 IO 的瞬时故障：后端不可达（timeout / connect / 5xx）与 LLM 网关限流 / 超时 / 5xx
IO_RETRYABLE: tuple[type[BaseException], ...] = (
    TimeoutError,
    BackendUnreachableError,
    httpx.TimeoutException,
    httpx.ConnectError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
    OutputParserException,
    ValidationError,
    EvidenceError,
)

_IO_NODE_FLAG = "__io_node__"


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, IO_RETRYABLE)


def io_node(fn: NodeFn[P]) -> NodeFn[P]:
    """只读 IO 节点装饰器：safe_node + 可重试异常穿透。必须配合 add_io_node 注册。"""
    wrapped = safe_node(fn, retryable=IO_RETRYABLE)
    setattr(wrapped, _IO_NODE_FLAG, True)
    return wrapped


def io_retry_policy(
    *, max_attempts: int | None = None, initial_interval: float | None = None
) -> RetryPolicy:
    settings = get_settings()
    return RetryPolicy(
        max_attempts=max_attempts or settings.node_retry_max_attempts,
        initial_interval=(
            settings.node_retry_initial_interval_seconds
            if initial_interval is None
            else initial_interval
        ),
        backoff_factor=2.0,
        max_interval=4.0,
        jitter=True,
        retry_on=is_retryable,
    )


async def retry_exhausted_handler(state: Any, error: NodeError) -> dict[str, Any]:
    """节点级 error_handler：重试耗尽后把异常落成 ErrorInfo，与 @safe_node 的错误形状一致。"""
    exc = error.error
    emit_node_completed(node=error.node, status="error")
    return {
        "error": ErrorInfo(
            node=error.node,
            type=type(exc).__name__,
            message=str(exc),
            traceback="".join(traceback.format_exception(exc)),
        ),
        "trace": [TraceEntry(node=error.node, decision="error:retry_exhausted")],
    }


def add_io_node(
    g: StateGraph[Any, Any, Any, Any],
    name: str,
    fn: Callable[..., Awaitable[dict[str, Any]]],
    *,
    max_attempts: int | None = None,
    initial_interval: float | None = None,
    with_error_handler: bool = True,
) -> None:
    """注册只读 IO 节点：RetryPolicy + 重试耗尽兜底。fn 必须是 @io_node（否则可重试异常会被
    safe_node 吞掉，RetryPolicy 永远不触发——静默失效比没有更糟）。

    with_error_handler=False 用于异常本就该穿透给父节点 safe_node 的私有子图（ticker）。
    """
    if not getattr(fn, _IO_NODE_FLAG, False) and with_error_handler:
        raise TypeError(f"{name}: add_io_node 只接受 @io_node 装饰的节点函数")
    g.add_node(
        name,
        fn,
        retry_policy=io_retry_policy(max_attempts=max_attempts, initial_interval=initial_interval),
        error_handler=retry_exhausted_handler if with_error_handler else None,
    )


__all__ = [
    "IO_RETRYABLE",
    "add_io_node",
    "io_node",
    "io_retry_policy",
    "is_retryable",
    "retry_exhausted_handler",
]
