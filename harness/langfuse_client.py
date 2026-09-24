"""LangFuse SDK 单例封装（ADR 0014 D5）。

读 app.config.Settings：enable_langfuse / langfuse_base_url / langfuse_public_key / langfuse_secret_key。
- enable_langfuse=False 时：返回 None，所有调用走 no-op
- 真实启用时：返回 langfuse.langchain.CallbackHandler 单例
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_callback_handler: Any | None = None
_initialized: bool = False


def get_callback_handler() -> Any | None:
    """返回 LangFuse Callback Handler 单例，未启用时返回 None。

    返回值用于 LangGraph 的 .with_config(callbacks=[handler]) 自动 trace。
    """
    global _callback_handler, _initialized

    if _initialized:
        return _callback_handler

    _initialized = True

    from app.config import get_settings
    settings = get_settings()

    if not settings.enable_langfuse:
        logger.info("LangFuse disabled (enable_langfuse=false)")
        return None

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning(
            "LangFuse keys not set (langfuse_public_key / langfuse_secret_key); "
            "running without trace upload"
        )
        return None

    try:
        import os

        from app.observability.tracing import create_callback_handler

        # langfuse v4 CallbackHandler 只读 os.environ；把 Settings 值回填进去
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
        os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)

        _callback_handler = create_callback_handler()
        logger.info("LangFuse callback handler initialized base_url=%s", settings.langfuse_base_url)
        return _callback_handler

    except Exception as exc:  # noqa: BLE001
        logger.warning("LangFuse init failed: %s", exc)
        return None


def reset_for_test() -> None:
    """测试用：重置单例状态。"""
    global _callback_handler, _initialized
    _callback_handler = None
    _initialized = False
