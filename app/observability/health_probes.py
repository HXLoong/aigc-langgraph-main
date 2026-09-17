"""健康检查探测（D2.6 / Issue #72）。

4 个上游 probe：MySQL / LangFuse / LLM / Java 后端。
每个独立 timeout，单点慢不阻塞。失败时返回简短状态码，不泄漏内部细节。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

ProbeStatus = Literal["ok", "fail", "disabled"]

# 单个依赖的探测上限；3 秒可容纳冷启动时的首次连接、握手和查询开销。
PROBE_TIMEOUT_SECONDS = 3
# 4 个并行探测的整体上限；额外余量用于模块导入、任务调度和取消收尾。
READY_TOTAL_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class ProbeResult:
    target: Literal["mysql", "langfuse", "llm", "java_backend"]
    status: ProbeStatus
    error: str | None = None
    latency_ms: int | None = None


async def _timed(target: str, coro) -> tuple[ProbeStatus, str | None, int]:
    import time

    t0 = time.monotonic()
    try:
        await asyncio.wait_for(coro, timeout=PROBE_TIMEOUT_SECONDS)
        return "ok", None, int((time.monotonic() - t0) * 1000)
    except TimeoutError:
        return "fail", "timeout", int((time.monotonic() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001
        return "fail", type(exc).__name__, int((time.monotonic() - t0) * 1000)


async def probe_mysql() -> ProbeResult:
    """SELECT 1：saver 已接线时打 saver 自己的连接池（ADR 0024 D4），否则直连 checkpoint_mysql_uri。"""
    from app.checkpointer import factory as checkpointer_factory
    from app.config import get_settings

    async def _check() -> None:
        if checkpointer_factory.has_checkpointer_pool():
            await checkpointer_factory.probe_checkpointer()
            return

        from urllib.parse import urlparse

        import aiomysql

        uri = get_settings().checkpoint_mysql_uri
        if not uri:
            raise RuntimeError("no_uri")
        parsed = urlparse(uri)
        conn = await aiomysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username or "",
            password=parsed.password or "",
            db=(parsed.path or "/").lstrip("/") or None,
        )
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
        finally:
            conn.close()

    status, err, lat = await _timed("mysql", _check())
    return ProbeResult(target="mysql", status=status, error=err, latency_ms=lat)


async def probe_langfuse() -> ProbeResult:
    """GET {base}/api/public/health (跳过如果未启用)."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.enable_langfuse:
        return ProbeResult(target="langfuse", status="disabled")

    async def _check() -> None:
        import httpx

        base = settings.langfuse_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, trust_env=False) as c:
            r = await c.get(f"{base}/api/public/health")
            if r.status_code >= 500:
                raise RuntimeError(f"http_{r.status_code}")

    status, err, lat = await _timed("langfuse", _check())
    return ProbeResult(target="langfuse", status=status, error=err, latency_ms=lat)


async def probe_llm() -> ProbeResult:
    """探测 LLM endpoint 可达（不发补全，仅 TCP/HTTP 可达 + 鉴权头不报 500）."""
    from app.config import get_settings

    settings = get_settings()
    base = (settings.qwen_api_base or "").rstrip("/")
    if not base:
        return ProbeResult(target="llm", status="disabled")

    async def _check() -> None:
        import httpx

        # 探测 /models（OpenAI 兼容端点标准路径），需要鉴权头，能区分 key 失效 vs endpoint 不可达
        url = f"{base}/models"
        headers = (
            {"Authorization": f"Bearer {settings.qwen_api_key}"}
            if settings.qwen_api_key
            else None
        )
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, trust_env=False) as c:
            r = await c.get(url, headers=headers)
            if r.status_code == 401:
                raise RuntimeError("unauthorized")
            if r.status_code >= 500:
                raise RuntimeError(f"http_{r.status_code}")

    status, err, lat = await _timed("llm", _check())
    return ProbeResult(target="llm", status=status, error=err, latency_ms=lat)


async def probe_java_backend() -> ProbeResult:
    """调最轻量的 read endpoint counterparty/info/instrument-inference-prompt."""
    from app.config import get_settings
    from app.tools.auth import get_goats_auth_headers

    settings = get_settings()
    base = (settings.otc_api_base_url or "").rstrip("/")
    if not base:
        return ProbeResult(target="java_backend", status="disabled")

    async def _check() -> None:
        import httpx

        url = f"{base}/admin-api/counterparty/info/instrument-inference-prompt"
        headers = {"Content-Type": "application/json"}
        if settings.otc_api_secret:
            headers["Authorization"] = f"Bearer {settings.otc_api_secret}"
        headers.update(get_goats_auth_headers())
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, trust_env=False) as c:
            r = await c.get(url, headers=headers)
            if r.status_code >= 500:
                raise RuntimeError(f"http_{r.status_code}")
            payload = r.json()
            if not isinstance(payload, dict) or "code" not in payload:
                raise RuntimeError("bad_envelope")

    status, err, lat = await _timed("java_backend", _check())
    return ProbeResult(target="java_backend", status=status, error=err, latency_ms=lat)


async def run_all_probes() -> list[ProbeResult]:
    """4 个 probe 并行，整体不超过 READY_TOTAL_TIMEOUT_SECONDS。"""
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                probe_mysql(),
                probe_langfuse(),
                probe_llm(),
                probe_java_backend(),
                return_exceptions=False,
            ),
            timeout=READY_TOTAL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return [
            ProbeResult(target=t, status="fail", error="total_timeout")  # type: ignore[arg-type]
            for t in ("mysql", "langfuse", "llm", "java_backend")
        ]
    return list(results)


__all__ = [
    "ProbeResult",
    "ProbeStatus",
    "probe_mysql",
    "probe_langfuse",
    "probe_llm",
    "probe_java_backend",
    "run_all_probes",
]
