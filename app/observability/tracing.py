"""可观测性配置（OpenTelemetry + 可选 LangSmith）。"""
from __future__ import annotations

import logging
import os

from app.config import get_settings

logger = logging.getLogger(__name__)


def setup_observability(app) -> None:
    """在 FastAPI 启动时调用。"""
    settings = get_settings()

    # LangSmith 通过环境变量启用
    if settings.enable_langsmith and settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
        logger.info("LangSmith 已启用，project=%s", settings.langsmith_project)

    # OpenTelemetry FastAPI 自动埋点
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry FastAPI 埋点已启用")
    except Exception as e:
        logger.warning("OTel 埋点失败（可忽略）: %s", e)
