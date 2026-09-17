"""@safe_node 装饰器（ADR 0001 D5/D6）。

任何被 @safe_node 装饰的节点函数：
1. 异常被捕获后写入 state['error']，图不崩
2. 自动追加 TraceEntry 到 state['trace']（含 node 名 + elapsed_ms）
3. 节点函数本身保持纯函数（输入 state，输出 partial state dict）
"""
from __future__ import annotations

import functools
import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Overwrite

from app.graph.state import AgentState, ErrorInfo, TraceEntry
from app.observability.metrics import emit_node_completed

logger = logging.getLogger(__name__)


NodeFn = Callable[[AgentState], Awaitable[dict[str, Any]]]


def safe_node(
    fn: NodeFn | None = None,
    *,
    retryable: tuple[type[BaseException], ...] = (),
) -> Any:
    """LangGraph 节点装饰器。

    用法:
        @safe_node
        async def my_node(state: AgentState) -> dict[str, Any]:
            return {"intent": "place_order_request"}

    返回的 partial state dict 会被 LangGraph reducer 合并到全局 state。

    retryable：这些异常**不**就地兜底，而是打一次 retry 指标后原样抛出，交给注册时挂的
    LangGraph RetryPolicy 重试（ADR 0024 D3；只读 IO 节点用 app.graph.retry.io_node，
    写类节点永远不要传——超时后重试可能重复下单）。
    """
    if fn is None:
        return functools.partial(safe_node, retryable=retryable)

    @functools.wraps(fn)
    async def wrapper(state: AgentState) -> dict[str, Any]:
        node_name = fn.__name__
        t0 = time.perf_counter()

        try:
            update = await fn(state)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # 自动追加 trace（节点函数没自带 trace 字段时）。
            # ADR 0024 D2：ingest 用 Overwrite([...]) 重置一轮边界，追加要写进 Overwrite 内部
            raw_trace = update.get("trace")
            if isinstance(raw_trace, Overwrite):
                existing_trace: list[TraceEntry] = list(raw_trace.value or [])
                if not any(_is_same_node(entry, node_name) for entry in existing_trace):
                    existing_trace.append(TraceEntry(node=node_name, elapsed_ms=elapsed_ms))
                update["trace"] = Overwrite(existing_trace)
            else:
                existing_trace = update.setdefault("trace", [])
                if not any(_is_same_node(entry, node_name) for entry in existing_trace):
                    existing_trace.append(
                        TraceEntry(node=node_name, elapsed_ms=elapsed_ms)
                    )

            # C1.5 监控埋点：节点完成成功
            emit_node_completed(node=node_name, status="ok", elapsed_ms=elapsed_ms)

            return update

        except Exception as exc:  # noqa: BLE001 - safe_node 本就是兜底
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if retryable and isinstance(exc, retryable):
                # 穿透给 RetryPolicy；耗尽后由 retry_exhausted_handler 落 error
                logger.warning("node=%s retryable=%s: %s", node_name, type(exc).__name__, exc)
                emit_node_completed(node=node_name, status="retry", elapsed_ms=elapsed_ms)
                raise
            logger.exception("node=%s error=%s", node_name, exc)

            # C1.5 监控埋点：节点抛异常（cascade fail 源头）
            emit_node_completed(node=node_name, status="error", elapsed_ms=elapsed_ms)

            return {
                "error": ErrorInfo(
                    node=node_name,
                    type=type(exc).__name__,
                    message=str(exc),
                    traceback=traceback.format_exc(),
                ),
                "trace": [
                    TraceEntry(
                        node=node_name,
                        decision="error",
                        elapsed_ms=elapsed_ms,
                    )
                ],
            }

    return wrapper


def _is_same_node(entry: Any, node_name: str) -> bool:
    """支持 entry 是 TraceEntry / dict / 其他对象的鸭子类型判断。"""
    if isinstance(entry, TraceEntry):
        return entry.node == node_name
    if isinstance(entry, dict):
        return entry.get("node") == node_name
    return getattr(entry, "node", None) == node_name
