#!/usr/bin/env python3
"""Launch a local app with tool HTTP recording/replay. LLM/DB/attachments remain live."""
from __future__ import annotations

import argparse
import importlib
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from harness.http_tape import BorrowedTransport, RecordingTransport, ReplayTransport  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def injected_tool_clients(
    transport: httpx.AsyncBaseTransport, *, timeout: float,
) -> AsyncIterator[None]:
    """共享池覆盖业务与 GOATS 客户端；单独适配 set-intent 的独立连接。"""
    from app.tools import http_pool

    main: Any = importlib.import_module("app.main")

    if http_pool.get_shared_http_client() is not None:
        raise RuntimeError("tool tape requires its own application process and HTTP pool")
    original_message_factory = main.MessageClientHttpx
    try:
        await http_pool.open_shared_http_client(timeout=timeout, transport=transport)
        main.MessageClientHttpx = partial(
            original_message_factory, transport=BorrowedTransport(transport),
        )
        yield
    finally:
        main.MessageClientHttpx = original_message_factory
        await http_pool.close_shared_http_client()
        await transport.aclose()


def create_app(mode: str, tape: Path) -> Any:
    from app.config import get_settings
    from app.main import app

    settings = get_settings()
    if settings.dry_run_backend:
        raise ValueError("DRY_RUN_BACKEND must be false to record/replay actual tool HTTP")
    if urlsplit(settings.otc_api_base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("the Java application URL must be local")
    if mode not in {"record", "replay"}:
        raise ValueError("mode must be record or replay")
    if mode == "replay" and settings.request_idempotency:
        raise ValueError("工具回放需 REQUEST_IDEMPOTENCY=false，避免缓存响应绕过录制请求")
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def tape_lifespan(application: Any) -> AsyncIterator[None]:
        transport = RecordingTransport(tape) if mode == "record" else ReplayTransport(tape)
        async with injected_tool_clients(transport, timeout=settings.backend_timeout_seconds):
            logger.info("tool_http_tape mode=%s; LLM/attachments/Langfuse/MySQL are outside tape", mode)
            async with original_lifespan(application):
                yield

    app.router.lifespan_context = tape_lifespan
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("record", "replay"))
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8202)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_app(args.mode, args.tape), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
