"""LangFuse SDK 单例封装（ADR 0014 D8）。

读 ENABLE_LANGFUSE / LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY。
- ENABLE_LANGFUSE 未启用时：返回 None，所有调用走 no-op
- 真实启用时：返回 langfuse.langchain.CallbackHandler 单例
"""
from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=False)

logger = logging.getLogger(__name__)

_callback_handler: Any | None = None
_initialized: bool = False


def _is_enabled() -> bool:
    return os.environ.get("ENABLE_LANGFUSE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_callback_handler() -> Any | None:
    """返回 LangFuse Callback Handler 单例，未启用时返回 None。

    返回值用于 LangGraph 的 .with_config(callbacks=[handler]) 自动 trace。
    """
    global _callback_handler, _initialized

    if _initialized:
        return _callback_handler

    _initialized = True

    if not _is_enabled():
        logger.info("LangFuse disabled (ENABLE_LANGFUSE != 'true')")
        return None

    try:
        from langfuse.langchain import CallbackHandler  # type: ignore[import-not-found]

        # langfuse v4：从环境变量自动读取 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
        if not (public_key and secret_key):
            logger.warning(
                "LangFuse keys not set (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY); "
                "running without trace upload"
            )
            return None

        _callback_handler = CallbackHandler()
        host = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
        logger.info("LangFuse callback handler initialized host=%s", host)
        return _callback_handler

    except Exception as exc:  # noqa: BLE001
        logger.warning("LangFuse init failed: %s", exc)
        return None


def reset_for_test() -> None:
    """测试用：重置单例状态。"""
    global _callback_handler, _initialized
    _callback_handler = None
    _initialized = False
