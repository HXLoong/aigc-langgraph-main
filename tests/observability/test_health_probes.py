"""健康检查 probe + 路由测试。"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.observability import health_probes as hp
from app.observability.health_probes import ProbeResult, run_all_probes


@pytest.fixture(autouse=True)
def reset_collector() -> None:
    from app.observability import metrics

    metrics.get_collector().reset()
    yield
    metrics.get_collector().reset()


# ============================================================
# /health · liveness
# ============================================================


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "otc-agent-langgraph"


@pytest.mark.parametrize(("dry_run", "mode"), [(False, "real"), (True, "dry-run")])
def test_health_reports_backend_mode(monkeypatch: pytest.MonkeyPatch, dry_run: bool, mode: str) -> None:
    """ADR 0024 D6：harness `--backend` 真生效的前提是服务端如实报告自己的写类拦截模式。"""
    from app import config as config_mod
    from app.api import health as health_mod

    settings = config_mod.get_settings().model_copy(update={"dry_run_backend": dry_run})
    monkeypatch.setattr(health_mod, "get_settings", lambda: settings)
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["backend_mode"] == mode


# ============================================================
# /ready · readiness · 分支覆盖
# ============================================================


def _stub_probe(target: str, status: str = "ok", error: str | None = None):
    async def _f() -> ProbeResult:
        return ProbeResult(target=target, status=status, error=error, latency_ms=10)  # type: ignore[arg-type]

    return _f


def test_ready_all_green_returns_200() -> None:
    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse")),
        patch.object(hp, "probe_llm", _stub_probe("llm")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend")),
        TestClient(app) as client,
    ):
        r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"] == {
        "mysql": "ok",
        "langfuse": "ok",
        "llm": "ok",
        "java_backend": "ok",
    }


def test_ready_mysql_down_returns_503() -> None:
    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql", "fail", "ConnectionRefusedError")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse")),
        patch.object(hp, "probe_llm", _stub_probe("llm")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend")),
        TestClient(app) as client,
    ):
        r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["mysql"] == "fail"
    assert body["checks"]["java_backend"] == "ok"


def test_ready_langfuse_disabled_still_returns_200() -> None:
    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse", "disabled")),
        patch.object(hp, "probe_llm", _stub_probe("llm")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend")),
        TestClient(app) as client,
    ):
        r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["langfuse"] == "disabled"


def test_ready_java_backend_fail_returns_503() -> None:
    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse")),
        patch.object(hp, "probe_llm", _stub_probe("llm")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend", "fail", "timeout")),
        TestClient(app) as client,
    ):
        r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["java_backend"] == "fail"


def test_ready_llm_timeout_is_soft_dependency() -> None:
    """ADR 0024 D5：LLM / LangFuse 是软依赖——失败只进 body（degraded）但保持 200，
    否则可选观测依赖或上游抖动会把业务 Pod 摘出负载均衡。"""
    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse")),
        patch.object(hp, "probe_llm", _stub_probe("llm", "fail", "TimeoutError")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend")),
        TestClient(app) as client,
    ):
        r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["llm"] == "fail"


def test_ready_langfuse_fail_is_soft_dependency() -> None:
    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse", "fail", "ConnectError")),
        patch.object(hp, "probe_llm", _stub_probe("llm")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend")),
        TestClient(app) as client,
    ):
        r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"


def test_ready_emits_health_check_metric() -> None:
    from app.observability import metrics

    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse", "disabled")),
        patch.object(hp, "probe_llm", _stub_probe("llm", "fail", "timeout")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend")),
        TestClient(app) as client,
    ):
        client.get("/ready")

    coll = metrics.get_collector()
    assert (
        coll.get_counter("otc_agent_health_check_total", {"target": "mysql", "status": "ok"}) == 1
    )
    assert (
        coll.get_counter(
            "otc_agent_health_check_total", {"target": "langfuse", "status": "disabled"}
        )
        == 1
    )
    assert (
        coll.get_counter("otc_agent_health_check_total", {"target": "llm", "status": "fail"}) == 1
    )


# ============================================================
# probe 内部行为
# ============================================================


@pytest.mark.asyncio
async def test_timed_catches_timeout() -> None:
    async def _slow() -> None:
        await asyncio.sleep(10)

    status, err, _ = await hp._timed("x", _slow())
    assert status == "fail"
    assert err == "timeout"


@pytest.mark.asyncio
async def test_timed_catches_exception() -> None:
    async def _raise() -> None:
        raise ValueError("nope")

    status, err, _ = await hp._timed("x", _raise())
    assert status == "fail"
    assert err == "ValueError"


@pytest.mark.asyncio
async def test_run_all_probes_returns_4_results() -> None:
    """run_all_probes 在所有 probe stub 之后应当返回 4 条。"""
    with (
        patch.object(hp, "probe_mysql", _stub_probe("mysql")),
        patch.object(hp, "probe_langfuse", _stub_probe("langfuse")),
        patch.object(hp, "probe_llm", _stub_probe("llm")),
        patch.object(hp, "probe_java_backend", _stub_probe("java_backend")),
    ):
        results = await run_all_probes()
    assert len(results) == 4
    assert {r.target for r in results} == {"mysql", "langfuse", "llm", "java_backend"}
