"""可观测性接入点（可选依赖 Langfuse）。

Langfuse 是**可选依赖**：本模块是它唯一的接入点，`app/` 下其它位置一律不得
`import langfuse`。

三条约束：

1. 所有 langfuse import 都在同一个 `try` 内 —— 失败只 warning 并降级，绝不阻断业务
2. 进程级 client 单例 —— 不在请求路径上重复构造
3. 对外只暴露 `RequestTrace`，不含任何 langfuse 类型

两个 ID 的归属必须分清：

- `request_trace_id`：业务审计 ID，调用方生成，贯穿 `node_trace.trace_id` 与
  `config.metadata.trace_id`（ADR 0004/#156）—— **恒定存在**
- `RequestTrace.langfuse_trace_id`：LangFuse 侧 Trace ID —— **可能不存在**
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_TRACEPARENT_RE = re.compile(
    r"^00-(?P<trace_id>[0-9a-f]{32})-(?P<span_id>[0-9a-f]{16})-[0-9a-f]{2}$"
)

#: 进程级 LangFuse client 单例（懒惰创建）
_langfuse_client: Any | None = None


@dataclass(frozen=True, slots=True)
class RequestTrace:
    """一次请求的 LangFuse 接入结果；不暴露任何 langfuse 类型。

    Attributes:
        handler: 可直接放进 `config["callbacks"]` 的回调；None 表示未接入
        langfuse_trace_id: LangFuse 侧 Trace ID；None 表示未接入
        url: LangFuse 跳转链接；None 表示未接入（或父 Trace 模式不适用）
    """

    handler: Any | None = None
    langfuse_trace_id: str | None = None
    url: str | None = None


def parse_traceparent(value: str | None) -> tuple[str, str] | None:
    """解析 W3C traceparent（`00-<32hex trace_id>-<16hex span_id>-<2hex flags>`）。

    格式非法或全零 ID 返回 None。
    """
    match = _TRACEPARENT_RE.fullmatch(value or "")
    if match is None:
        return None
    trace_id = match.group("trace_id")
    span_id = match.group("span_id")
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return trace_id, span_id


def _enabled() -> bool:
    """LangFuse 是否具备启用条件（开关 + 双 key；ADR 0024 D5：所有环境同一条请求级路径）。"""
    settings = get_settings()
    return bool(
        settings.enable_langfuse
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )


def _ensure_client() -> Any | None:
    """懒惰创建并缓存进程级 Langfuse client；不可用时返回 None。

    不依赖 FastAPI 启动钩子 —— eval / harness / 测试都会直接调图。
    """
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client
    if not _enabled():
        return None
    settings = get_settings()
    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_base_url,
            environment=getattr(settings, "environment", None) or "default",
        )
    except ImportError as exc:
        logger.warning("langfuse 未安装或版本不兼容：%s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - tracing 失败不阻断业务
        logger.warning("Langfuse client 初始化失败：%s", exc)
        return None
    return _langfuse_client


async def attach_request_trace(
    *, request_trace_id: str, traceparent: str | None
) -> RequestTrace:
    """把请求接到 LangFuse（自建 Trace 或接入外部父 Trace）。

    未启用或出现任何 langfuse 异常都返回空 `RequestTrace` —— 本函数**不抛异常**。

    Args:
        request_trace_id: 业务审计 ID；自建 Trace 时复用为 LangFuse Trace ID，
            保证 `node_trace.trace_id` 与 LangFuse trace 同值可直查（ADR 0004/#156）
        traceparent: 调用方传入的 W3C traceparent；仅 `trust_inbound_traceparent=true`
            时生效（测试工作台等可信网络），否则恒被忽略
    """
    settings = get_settings()
    if not _enabled():
        return RequestTrace()

    # 信任边界由独立开关承担（ADR 0024 D5）；注入只影响 trace 归属，不影响业务数据
    parent_context = (
        parse_traceparent(traceparent)
        if getattr(settings, "trust_inbound_traceparent", False)
        else None
    )
    langfuse_trace_id = parent_context[0] if parent_context else request_trace_id

    # 必须先注册进程级 client：CallbackHandler(public_key=) 内部 get_client 只在已注册实例里查，
    # 查不到会静默返回 tracing_enabled=False 的假 client（首次请求 / 父 Trace 分支曾因此丢 trace）
    client = _ensure_client()
    if client is None:
        return RequestTrace()

    try:
        from langfuse.langchain import CallbackHandler
        from langfuse.types import TraceContext

        trace_context: TraceContext = {"trace_id": langfuse_trace_id}
        if parent_context:
            trace_context["parent_span_id"] = parent_context[1]

        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            trace_context=trace_context,
        )
    except Exception as exc:  # noqa: BLE001 - tracing 失败不阻断业务
        logger.warning("LangFuse trace 接入失败：%s", exc)
        return RequestTrace()

    if parent_context:
        # 父 Trace 由调用方创建并持有链接，这里不重复查询
        return RequestTrace(handler=handler, langfuse_trace_id=langfuse_trace_id)

    url: str | None = None
    try:
        url = await asyncio.to_thread(client.get_trace_url, trace_id=langfuse_trace_id)
    except Exception as exc:  # noqa: BLE001 - 链接失败不影响 trace 上报
        logger.warning("LangFuse trace 链接不可用：%s", exc)
    return RequestTrace(handler=handler, langfuse_trace_id=langfuse_trace_id, url=url)


__all__ = ["RequestTrace", "attach_request_trace", "parse_traceparent"]
