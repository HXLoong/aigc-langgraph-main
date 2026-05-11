"""FastAPI 入口（ADR 0001 D6 + ADR 0014 D8）。

启动时：
- 编译主图 + 挂载到 app.state
- 注册 LangFuse callback handler（如 ENABLE_LANGFUSE=true）
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api.routes import router as api_router
from app.graph.main import build_main_graph

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

    # M1 阶段：不强制 checkpointer（M2/M3 接入 AIOMySQLSaver）
    app.state.main_graph = build_main_graph(checkpointer=None)
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

    logger.info("stopping otc-agent-langgraph")


app = FastAPI(
    title="otc-agent-langgraph",
    description="场外衍生品 AI 指令助手 — LangGraph 替换 Dify",
    version="0.2.0-m1",
    lifespan=lifespan,
)

app.include_router(api_router)
