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
from typing import Any, ParamSpec, overload

from langgraph.types import Overwrite

from app.extraction.locks import protect_update
from app.graph.state import ErrorInfo, TraceEntry
from app.observability.metrics import emit_node_completed
from app.observability.tracing import report_handled_error

logger = logging.getLogger(__name__)


P = ParamSpec("P")
NodeFn = Callable[P, Awaitable[dict[str, Any]]]


@overload
def safe_node(fn: NodeFn[P], *, retryable: tuple[type[BaseException], ...] = ()) -> NodeFn[P]: ...


@overload
def safe_node(fn: None = None, *, retryable: tuple[type[BaseException], ...] = ()) -> Callable[[NodeFn[P]], NodeFn[P]]: ...


def safe_node(
    fn: NodeFn[P] | None = None,
    *,
    retryable: tuple[type[BaseException], ...] = (),
) -> NodeFn[P] | Callable[[NodeFn[P]], NodeFn[P]]:
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
        def decorate(node: NodeFn[P]) -> NodeFn[P]:
            return safe_node(node, retryable=retryable)
        return decorate

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
        node_name = fn.__name__
        t0 = time.perf_counter()

        try:
            update = await fn(*args, **kwargs)
            state = args[0] if args else kwargs.get("state")
            if isinstance(state, dict):
                update = protect_update(state, update)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # 自动追加 trace（节点函数没自带 trace 字段时）。
            # ADR 0024 D2：ingest 用 Overwrite([...]) 重置一轮边界，追加要写进 Overwrite 内部
            raw_trace = update.get("trace")
            if isinstance(raw_trace, Overwrite):
                existing_trace: list[TraceEntry] = list(raw_trace.value or [])
                if not any(_is_same_node(entry, node_name) for entry in existing_trace):
                    existing_trace.append(TraceEntry(node=node_name, elapsed_ms=elapsed_ms))
                update["trace"] = Overwrite(_stamp_elapsed(existing_trace, node_name, elapsed_ms))
            else:
                existing_trace = update.setdefault("trace", [])
                if not any(_is_same_node(entry, node_name) for entry in existing_trace):
                    existing_trace.append(
                        TraceEntry(node=node_name, elapsed_ms=elapsed_ms)
                    )
                update["trace"] = _stamp_elapsed(existing_trace, node_name, elapsed_ms)

            # C1.5 监控埋点：节点完成成功
            emit_node_completed(node=node_name, status="ok", elapsed_ms=elapsed_ms)

            return update

        except Exception as exc:  # noqa: BLE001 - safe_node 本就是兜底
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if retryable and isinstance(exc, retryable):
                # 穿透给 RetryPolicy；耗尽后由 retry_exhausted_handler 落 error
                logger.warning("node=%s retryable=%s", node_name, type(exc).__name__)
                emit_node_completed(node=node_name, status="retry", elapsed_ms=elapsed_ms)
                raise
            logger.exception("node=%s error=%s", node_name, type(exc).__name__)

            # C1.5 监控埋点：节点抛异常（cascade fail 源头）
            emit_node_completed(node=node_name, status="error", elapsed_ms=elapsed_ms)

            failed = {
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
            report_handled_error(failed)
            return failed

    return wrapper


def _stamp_elapsed(entries: list[Any], node_name: str, elapsed_ms: int) -> list[Any]:
    """单一计时（ADR 0024 D5）：节点自己写的本节点条目缺 elapsed_ms 时补上，否则
    node_trace.duration_ms 恒 NULL；已有值与其它节点的条目不动。"""
    stamped: list[Any] = []
    for entry in entries:
        if _is_same_node(entry, node_name):
            if isinstance(entry, TraceEntry) and entry.elapsed_ms is None:
                entry = entry.model_copy(update={"elapsed_ms": elapsed_ms})
            elif isinstance(entry, dict) and entry.get("elapsed_ms") is None:
                entry = {**entry, "elapsed_ms": elapsed_ms}
        stamped.append(entry)
    return stamped


def _is_same_node(entry: Any, node_name: str) -> bool:
    """支持 entry 是 TraceEntry / dict / 其他对象的鸭子类型判断。"""
    if isinstance(entry, TraceEntry):
        return entry.node == node_name
    if isinstance(entry, dict):
        return entry.get("node") == node_name
    return getattr(entry, "node", None) == node_name
