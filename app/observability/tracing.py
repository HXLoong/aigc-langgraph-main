"""可观测性配置（OpenTelemetry + 可选 Langfuse）。"""
from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

# 全局 Langfuse 回调实例，供 LangChain / LangGraph 调用时注入
_langfuse_handler = None


def get_langfuse_handler():
    """返回全局 CallbackHandler，未启用时返回 None。"""
    return _langfuse_handler


def setup_observability(app) -> None:
    """在 FastAPI 启动时调用。"""
    global _langfuse_handler
    settings = get_settings()

    if settings.enable_langfuse and settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            # langfuse 4.x：先初始化全局 client，再从 langchain 子模块取 CallbackHandler
            from langfuse import Langfuse
            from langfuse.langchain import CallbackHandler

            Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            _langfuse_handler = CallbackHandler()
            logger.info(
                "Langfuse 已启用，host=%s project=%s",
                settings.langfuse_host, settings.langfuse_project,
            )
        except ImportError as e:
            logger.warning("langfuse 未安装或版本不兼容：%s", e)
        except Exception as e:
            logger.warning("Langfuse 初始化失败：%s", e)

    # OpenTelemetry FastAPI 自动埋点
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry FastAPI 埋点已启用")
    except Exception as e:
        logger.warning("OTel 埋点失败（可忽略）: %s", e)
