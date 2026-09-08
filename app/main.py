"""FastAPI 入口（ADR 0001 D6 + ADR 0014 D8）。

启动时：
- 编译主图 + 挂载到 app.state
- 注册 LangFuse callback handler（如 ENABLE_LANGFUSE=true）
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.health import router as health_router
from app.api.routes import router as api_router
from app.checkpointer.factory import close_checkpointer, init_checkpointer
from app.config import get_settings
from app.graph.main import build_main_graph
from app.observability.metrics import emit_http_response, get_collector
from app.tools.message_client import MessageClientHttpx

logger = logging.getLogger(__name__)


def _is_enabled(env_key: str, default: bool = False) -> bool:
    raw = os.environ.get(env_key, "").strip().lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """编译主图 + LangFuse 接入。"""
    logger.info("starting otc-agent-langgraph")

    # #153 裁决（ADR 0009/0021）：checkpointer 接线——多轮状态持久化是生产正确性。
    # 显式启用即硬依赖（init 失败直接抛，不静默降级）；生产未启用 fail-fast。
    settings = get_settings()
    checkpointer = None
    if getattr(settings, "use_mysql_checkpointer", False):
        checkpointer = await init_checkpointer()
        logger.info("AIOMySQLSaver checkpointer 已接线")
    elif getattr(settings, "environment", "") == "production":
        raise RuntimeError(
            "生产环境必须启用 MySQL checkpointer（USE_MYSQL_CHECKPOINTER=true，"
            "见 ADR 0021 / issue #153）"
        )
    message_client_factory = (
        None if settings.environment == "development" else MessageClientHttpx
    )
    if message_client_factory is None:
        logger.info("development environment: intent persistence disabled")
    app.state.main_graph = build_main_graph(
        checkpointer=checkpointer,
        message_client_factory=message_client_factory,
        attach_langfuse_callbacks=settings.environment != "development",
    )
    logger.info("main graph compiled")

    if _is_enabled("ENABLE_LANGFUSE"):
        try:
            from harness.langfuse_client import get_callback_handler

            handler = get_callback_handler()
            app.state.langfuse_handler = handler
            logger.info("LangFuse callback handler registered")
        except Exception as exc:  # noqa: BLE001 - 不让 LangFuse 失败导致服务起不来
            logger.warning("LangFuse init skipped: %s", exc)
            app.state.langfuse_handler = None
    else:
        app.state.langfuse_handler = None

    yield

    if checkpointer is not None:
        await close_checkpointer()
    logger.info("stopping otc-agent-langgraph")


app = FastAPI(
    title="otc-agent-langgraph",
    description="场外衍生品 AI 指令助手 — LangGraph 替换 Dify",
    version="0.2.0-m1",
    lifespan=lifespan,
)


# 探测路径不计入 HTTP 指标（频次极高会稀释告警分母 + 增 metrics cardinality）
# /metrics 自计入会产生循环依赖（scrape 自己 → 计数 → 下次 scrape 看到自己）
_METRICS_EXCLUDED_PATHS: frozenset[str] = frozenset({
    "/metrics",
    "/health",
    "/ready",
})


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    """统计每个 HTTP 响应的 status_class（ADR 0019 P0 5xx 告警依赖）。

    设计：
    - 异常路径也计入 5xx：unhandled exception → starlette 返回 500，
      middleware 在 except 里手工 emit 后重新抛
    - path 用 request.url.path 原样（FastAPI 路由模式已是 pattern）
    - 探测路径（/health / /ready / /metrics）排除
    - emit 失败不影响业务（emit_http_response 内部已 try）
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        excluded = path in _METRICS_EXCLUDED_PATHS
        try:
            response = await call_next(request)
        except Exception:
            if not excluded:
                emit_http_response(path=path, status_class="5xx")
            raise
        if not excluded:
            status_class = f"{response.status_code // 100}xx"
            emit_http_response(path=path, status_class=status_class)
        return response


app.add_middleware(HTTPMetricsMiddleware)

app.include_router(api_router)
app.include_router(health_router)


@app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics() -> str:
    """Prometheus 兼容指标端点（C1.5 / Issue #50）。

    返回 text/plain 格式的 exposition，可被 Prometheus / VictoriaMetrics 抓取。
    监控面板字段说明见 docs/observability.md。
    """
    return get_collector().render_prometheus()
