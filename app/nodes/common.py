"""节点工具：装饰器、辅助函数。"""
from __future__ import annotations

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.state import AgentState, TraceEntry, preview

logger = logging.getLogger(__name__)

NodeFunc = Callable[[AgentState], Awaitable[dict[str, Any]]]


def safe_node(fn: NodeFunc) -> NodeFunc:
    """节点异常捕获装饰器。

    职责：
    1. 捕获节点异常，避免整图崩溃
    2. 自动生成 trace 记录（含耗时）
    3. 错误信息写入 state['error']，由下游 render 节点统一处理
    """
    @functools.wraps(fn)
    async def wrapper(state: AgentState) -> dict[str, Any]:
        node_name = fn.__name__
        start = time.monotonic()
        try:
            result = await fn(state)
            duration = int((time.monotonic() - start) * 1000)
            trace: TraceEntry = {
                "node": node_name,
                "status": "success",
                "duration_ms": duration,
                "output_preview": preview(result),
            }
            if "trace" not in result:
                result["trace"] = [trace]
            else:
                # 节点自己也加了 trace，追加
                result["trace"] = [*result["trace"], trace]
            return result
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            logger.exception("节点 %s 执行失败", node_name)
            return {
                "error": f"{node_name}: {type(exc).__name__}: {exc}",
                "trace": [
                    TraceEntry(
                        node=node_name,
                        status="error",
                        duration_ms=duration,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ],
            }
    return wrapper
