"""健康检查端点。

GET /health  · liveness  · 仅检查进程存活，无外部依赖
GET /ready   · readiness · 4 个上游并发探测（MySQL/LangFuse/LLM/Java 后端）

硬依赖（mysql / java_backend）失败 → 503 摘流量；软依赖（langfuse / llm）失败只进 body
（status=degraded，仍 200）——可选观测依赖或上游抖动不能把业务 Pod 摘出负载均衡（ADR 0024 D5）。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.observability.health_probes import run_all_probes
from app.observability.metrics import get_collector

router = APIRouter(tags=["health"])

_METRIC_HEALTH_CHECK_TOTAL = "otc_agent_health_check_total"
#: 失败即 503 的硬依赖；其余探针为软依赖
HARD_DEPENDENCIES: frozenset[str] = frozenset({"mysql", "java_backend"})


@router.get("/health", include_in_schema=True)
async def health() -> dict[str, str]:
    # backend_mode：写类后端调用是否被 dry-run 拦截（ADR 0024 D6：harness --backend 据此把关）
    mode = "dry-run" if get_settings().dry_run_backend else "real"
    return {"status": "ok", "service": "otc-agent-langgraph", "backend_mode": mode}


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
    hard_fail = any(r.status == "fail" and r.target in HARD_DEPENDENCIES for r in results)
    body = {
        "status": "degraded" if any_fail else "ok",
        "checks": checks,
    }
    return JSONResponse(body, status_code=503 if hard_fail else 200)


__all__ = ["router"]
