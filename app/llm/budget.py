"""单次工具调用的模型请求额度；子任务共享对象，内部嵌套不能重置。"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock

import httpx


class ModelRequestLimitError(RuntimeError):
    """本次调用已发起模型请求，禁止再次派发。"""


@dataclass
class ModelRequestBudget:
    """计数仅覆盖真实请求尝试，失败不返还额度。"""

    requests: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def claim(self) -> None:
        """派发前原子占用，保护异步子任务及线程继承的同一额度。"""
        with self._lock:
            if self.requests:
                raise ModelRequestLimitError("本次工具调用最多允许一次模型请求")
            self.requests += 1


_current_budget: ContextVar[ModelRequestBudget | None] = ContextVar("model_request_budget", default=None)


@contextmanager
def model_request_scope() -> Iterator[ModelRequestBudget]:
    """入口创建额度；内部借用已有额度，退出后恢复调用方上下文。"""
    existing = _current_budget.get()
    if existing is not None:
        yield existing
        return
    budget = ModelRequestBudget()
    token = _current_budget.set(budget)
    try:
        yield budget
    finally:
        _current_budget.reset(token)


def before_model_request(request: httpx.Request) -> None:
    """统一 HTTP 客户端在发送模型 POST 前占用调用额度。"""
    budget = _current_budget.get()
    # 能力探针等非业务调用没有工具调用上下文；业务与节点 API 必须建立作用域。
    if request.method == "POST" and budget is not None:
        budget.claim()


async def before_async_model_request(request: httpx.Request) -> None:
    """异步 HTTP hook 复用同一计数，结构化输出与流式请求同样受约束。"""
    before_model_request(request)
