"""结构化日志（ADR 0024 D5）：structlog 接管 stdlib logging，请求上下文经 contextvars 进每条日志。

- 业务代码继续用 `logging.getLogger(__name__)` + `%` 格式化，不需要改写；
  根 handler 的 `ProcessorFormatter` 把 stdlib 记录渲染成 JSON（生产）或彩色控制台（开发）
- `bound_request_context(trace_id=..., conversation_id=..., message_id=...)` 在 routes 里包住
  一次图调用，期间任何模块、任何节点打的日志都自动带这三个键——排障时按 trace_id 一把捞
- 级别与格式来自 Settings（LOG_LEVEL / LOG_FORMAT，auto = development 控制台、其余 JSON）
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any, Literal

import structlog

from app.config import Settings
from app.observability.privacy import redact_log

LogFormat = Literal["json", "console"]
_HANDLER_TAG = "_otc_structlog_handler"


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_log,
    ]


def resolve_format(settings: Settings) -> LogFormat:
    if settings.log_format != "auto":
        return settings.log_format
    return "console" if settings.environment == "development" else "json"


def configure_logging(
    *, level: str = "INFO", fmt: LogFormat = "json", stream: IO[str] | None = None
) -> None:
    """幂等：重复调用替换本模块装的根 handler，不动 uvicorn 自己的 handler。"""
    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if fmt == "json"
        else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_shared_processors(),
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)
    setattr(handler, _HANDLER_TAG, True)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, _HANDLER_TAG, False):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    structlog.configure(
        processors=[*_shared_processors(), structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


def configure_logging_from_settings(settings: Settings) -> None:
    configure_logging(level=settings.log_level, fmt=resolve_format(settings))


@contextmanager
def bound_request_context(**context: Any) -> Iterator[None]:
    """把请求级键绑进 contextvars；退出时只解绑自己绑的键。"""
    bound = {k: v for k, v in context.items() if v is not None}
    structlog.contextvars.bind_contextvars(**bound)
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars(*bound)


__all__ = [
    "LogFormat",
    "bound_request_context",
    "configure_logging",
    "configure_logging_from_settings",
    "resolve_format",
]
