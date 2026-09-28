"""LangFuse SDK 单例封装（ADR 0014 D5）。

读 app.config.Settings：enable_langfuse / langfuse_base_url / langfuse_public_key / langfuse_secret_key。
- enable_langfuse=False 时：返回 None，所有调用走 no-op
- 真实启用时：创建用例 / HTTP 轮 Observation，经请求头连接服务端 trace
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_client: Any | None = None
_experiment_parent: ContextVar[bool] = ContextVar("experiment_parent", default=False)


@contextmanager
def experiment_item_trace(*, active: bool = True) -> Iterator[None]:
    """仅 SDK Experiment item 明确允许继承其父观测，其它用例建立独立 Trace。"""
    token = _experiment_parent.set(active)
    try:
        yield
    finally:
        _experiment_parent.reset(token)


def get_client() -> Any | None:
    """复用进程级 SDK 客户端，所有评测入口遵守同一配置和关闭开关。"""
    from app.config import get_settings

    settings = get_settings()
    if not settings.enable_langfuse or not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    global _client
    if _client is None:
        try:
            from langfuse import Langfuse

            _client = Langfuse(
                public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key,
                base_url=settings.langfuse_base_url, environment=settings.environment,
                timeout=settings.langfuse_timeout_seconds, flush_at=settings.langfuse_flush_at,
            )
        except Exception as exc:
            logger.warning("评测追踪不可用：%s", type(exc).__name__)
    return _client


@dataclass
class CaseTrace:
    """用例追踪句柄；关闭追踪时字段为空，业务执行仍可继续。"""

    trace_id: str | None = None
    observation_id: str | None = None
    observation: Any | None = None

    def update(self, output: dict[str, Any]) -> None:
        """记录用例结果，观测故障只告警，不改变业务回归结果。"""
        if self.observation is not None:
            try:
                self.observation.update(output=output)
            except Exception as exc:
                logger.warning("用例追踪结果未写入：%s", type(exc).__name__)


@contextmanager
def case_trace(
    case_id: str, conversation_id: str, user_id: str, *,
    metadata: dict[str, Any] | None = None,
    case_input: dict[str, Any] | None = None,
) -> Iterator[CaseTrace]:
    """创建用例根，立即为根与后续 Observation 设置同一 Session。"""
    result = CaseTrace()
    with ExitStack() as stack:
        client = get_client()
        if client is not None:
            try:
                from langfuse import propagate_attributes
                from opentelemetry import context as otel_context

                # 工作台外层可能已有观测；独立用例不能误接到共享批次 Trace。
                if not _experiment_parent.get():
                    token = otel_context.attach(otel_context.Context())
                    stack.callback(otel_context.detach, token)

                # 1. 先更新可能存在的 Experiment 根，再让新建用例根继承属性。
                stack.enter_context(propagate_attributes(session_id=conversation_id, user_id=user_id))
                observation = stack.enter_context(client.start_as_current_observation(
                    name="regression_case", as_type="chain",
                    input=case_input,
                    metadata={"case_id": case_id, **(metadata or {})},
                ))
                # 2. 调用方保存句柄，后续每轮 HTTP 都自然继承同一 Session。
                result = CaseTrace(observation.trace_id, observation.id, observation)
            except Exception as exc:
                logger.warning("用例追踪初始化失败：%s", type(exc).__name__)
        yield result


@contextmanager
def http_turn_trace(index: int) -> Iterator[dict[str, str]]:
    """为一轮 HTTP 调用创建父 Observation，仅向应用请求传递 W3C 头。"""
    headers: dict[str, str] = {}
    with ExitStack() as stack:
        client = get_client()
        if client is not None:
            try:
                from opentelemetry.trace.propagation.tracecontext import (
                    TraceContextTextMapPropagator,
                )

                stack.enter_context(client.start_as_current_observation(
                    name="workflow_http", as_type="span", metadata={"turn": index},
                ))
                TraceContextTextMapPropagator().inject(headers)
            except Exception as exc:
                logger.warning("HTTP 追踪上下文不可用：%s", type(exc).__name__)
        yield headers


def flush() -> None:
    """在批次结束后导出积累的追踪；不逐请求刷新。"""
    if _client is not None:
        try:
            _client.flush()
        except Exception as exc:
            logger.warning("评测追踪导出失败：%s", type(exc).__name__)


def record_business_score(report: dict[str, Any], *, metadata: dict[str, Any]) -> None:
    """把本地确定性结果写到已有用例 Trace，不另起孤立评分 Trace。"""
    client = get_client()
    if client is None or not report.get("langfuse_trace_id"):
        return
    try:
        client.create_score(
            name="det_business_pass", value=float(bool(report["passed"])), data_type="BOOLEAN",
            trace_id=report["langfuse_trace_id"], observation_id=report.get("observation_id"),
            comment="全部现有业务断言通过" if report["passed"] else "业务断言失败，字段差异见报告",
            metadata={**metadata, "case_id": report["case_id"],
                      "parameter_assertion_coverage": report.get("parameter_assertion_coverage")},
        )
    except Exception as exc:
        # 观测故障不篡改业务结果，报告明确表示评分未能排入导出队列。
        report["score_status"] = "enqueue_failed"
        logger.warning("业务评分未写入：%s", type(exc).__name__)
    else:
        report["score_status"] = "enqueued"
