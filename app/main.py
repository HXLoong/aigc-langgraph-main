"""FastAPI 应用入口。

职责：
- 配置日志
- lifespan 内：初始化 Checkpointer → 构建 Graph
- 关闭时：释放 Checkpointer 连接池
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.routes import router
from app.checkpointer.factory import close_checkpointer, init_checkpointer
from app.config import get_settings
from app.graphs.main_graph import build_main_graph
from app.observability.tracing import setup_observability


def _configure_logging() -> None:
    """结构化日志：控制台看得清，JSON 落 ES 也方便。"""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
            if settings.environment == "production"
            else structlog.dev.ConsoleRenderer(),
        ],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：Checkpointer → Graph；关闭：反序释放。"""
    logger = logging.getLogger(__name__)
    logger.info("应用启动中...")

    cp = await init_checkpointer()
    app.state.checkpointer = cp
    app.state.graph_app = build_main_graph(cp)

    logger.info("应用就绪")
    try:
        yield
    finally:
        logger.info("应用关闭中...")
        await close_checkpointer()
        logger.info("清理完成")


def create_app() -> FastAPI:
    _configure_logging()
    settings = get_settings()

    app = FastAPI(
        title="OTC Agent",
        description="场外衍生品 AI 指令助手",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(router)
    setup_observability(app)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "environment": settings.environment,
            "use_langgraph": settings.use_langgraph,
        }

    return app


app = create_app()
