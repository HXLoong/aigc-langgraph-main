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

from app.graph.state import AgentState, ErrorInfo, TraceEntry
from app.observability.metrics import emit_node_completed

logger = logging.getLogger(__name__)


NodeFn = Callable[[AgentState], Awaitable[dict[str, Any]]]


def safe_node(fn: NodeFn) -> NodeFn:
    """LangGraph 节点装饰器。

    用法:
        @safe_node
        async def my_node(state: AgentState) -> dict[str, Any]:
            return {"intent": "place_order_request"}

    返回的 partial state dict 会被 LangGraph reducer 合并到全局 state。
    """

    @functools.wraps(fn)
    async def wrapper(state: AgentState) -> dict[str, Any]:
        node_name = fn.__name__
        t0 = time.perf_counter()

        try:
            update = await fn(state)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # 自动追加 trace（节点函数没自带 trace 字段时）
            existing_trace: list[TraceEntry] = update.setdefault("trace", [])
            if not any(_is_same_node(entry, node_name) for entry in existing_trace):
                existing_trace.append(
                    TraceEntry(node=node_name, elapsed_ms=elapsed_ms)
                )

            # C1.5 监控埋点：节点完成成功
            emit_node_completed(node=node_name, status="ok", elapsed_ms=elapsed_ms)

            return update

        except Exception as exc:  # noqa: BLE001 - safe_node 本就是兜底
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
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
