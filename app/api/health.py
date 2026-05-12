"""健康检查端点（D2.6 / Issue #72）。

GET /health  · liveness  · 仅检查进程存活，无外部依赖
GET /ready   · readiness · 4 个上游并发探测（MySQL/LangFuse/LLM/Java 后端）
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.observability.health_probes import run_all_probes
from app.observability.metrics import get_collector

router = APIRouter(tags=["health"])

_METRIC_HEALTH_CHECK_TOTAL = "otc_agent_health_check_total"


@router.get("/health", include_in_schema=True)
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "otc-agent-langgraph"}


@router.get("/ready", include_in_schema=True)
async def ready() -> JSONResponse:
    results = await run_all_probes()
    collector = get_collector()

    checks: dict[str, str] = {}
    for r in results:
        checks[r.target] = r.status
        collector.inc_counter(
            _METRIC_HEALTH_CHECK_TOTAL,
            {"target": r.target, "status": r.status},
        )

    any_fail = any(r.status == "fail" for r in results)
    body = {
        "status": "degraded" if any_fail else "ok",
        "checks": checks,
    }
    return JSONResponse(body, status_code=503 if any_fail else 200)


__all__ = ["router"]
