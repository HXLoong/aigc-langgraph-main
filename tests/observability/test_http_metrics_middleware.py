"""HTTPMetricsMiddleware · ADR 0019 P0 5xx 告警的数据源测试。

测试范围：
- 探测路径排除（/health /ready /metrics 不计数）
- 业务路径计数：2xx / 4xx / 5xx 分类
- unhandled exception 计入 5xx 并重新抛
- alerts.py 能从 /metrics 文本读到 http_total / http_5xx
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.main import HTTPMetricsMiddleware
from app.observability.alerts import parse_prometheus_metrics
from app.observability.metrics import (
    METRIC_HTTP_RESPONSE_TOTAL,
    emit_http_response,
    get_collector,
)


@pytest.fixture(autouse=True)
def _reset_collector():
    """每个测试前清掉全局 collector 内 http counter，避免污染。"""
    coll = get_collector()
    coll._counters[METRIC_HTTP_RESPONSE_TOTAL].clear()
    yield
    coll._counters[METRIC_HTTP_RESPONSE_TOTAL].clear()


def _build_test_app() -> FastAPI:
    """构造一个独立 FastAPI app 挂 middleware，便于测试隔离。"""
    app = FastAPI()
    app.add_middleware(HTTPMetricsMiddleware)

    @app.get("/ok")
    def ok():  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    @app.get("/bad")
    def bad():  # type: ignore[no-untyped-def]
        raise HTTPException(status_code=400, detail="bad request")

    @app.get("/boom")
    def boom():  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom")

    @app.get("/health")
    def health():  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    @app.get("/ready")
    def ready():  # type: ignore[no-untyped-def]
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():  # type: ignore[no-untyped-def]
        return {"raw": "..."}

    return app


# ============================================================
# emit_http_response · 直接调用 + 标签维度
# ============================================================


def test_emit_http_response_increments_counter() -> None:
    emit_http_response(path="/v1/workflows/run", status_class="2xx")
    cnt = get_collector().get_counter(
        METRIC_HTTP_RESPONSE_TOTAL,
        {"path": "/v1/workflows/run", "status_class": "2xx"},
    )
    assert cnt == 1


def test_emit_http_response_distinct_status_classes() -> None:
    emit_http_response(path="/x", status_class="2xx")
    emit_http_response(path="/x", status_class="2xx")
    emit_http_response(path="/x", status_class="5xx")
    coll = get_collector()
    assert coll.get_counter(METRIC_HTTP_RESPONSE_TOTAL, {"path": "/x", "status_class": "2xx"}) == 2
    assert coll.get_counter(METRIC_HTTP_RESPONSE_TOTAL, {"path": "/x", "status_class": "5xx"}) == 1


# ============================================================
# Middleware · 业务路径计数
# ============================================================


def test_middleware_counts_2xx() -> None:
    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/ok")
        assert r.status_code == 200
    cnt = get_collector().get_counter(
        METRIC_HTTP_RESPONSE_TOTAL, {"path": "/ok", "status_class": "2xx"}
    )
    assert cnt == 1


def test_middleware_counts_4xx() -> None:
    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get("/bad")
        assert r.status_code == 400
    cnt = get_collector().get_counter(
        METRIC_HTTP_RESPONSE_TOTAL, {"path": "/bad", "status_class": "4xx"}
    )
    assert cnt == 1


def test_middleware_counts_unhandled_exception_as_5xx() -> None:
    """RuntimeError 触发 → starlette 返回 500，middleware 在 except 里 emit。"""
    app = _build_test_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/boom")
        assert r.status_code == 500
    cnt = get_collector().get_counter(
        METRIC_HTTP_RESPONSE_TOTAL, {"path": "/boom", "status_class": "5xx"}
    )
    assert cnt == 1


# ============================================================
# Middleware · 探测路径排除
# ============================================================


@pytest.mark.parametrize("path", ["/health", "/ready", "/metrics"])
def test_middleware_excludes_probe_paths(path: str) -> None:
    app = _build_test_app()
    with TestClient(app) as client:
        r = client.get(path)
        assert r.status_code == 200
    # 不应有任何对应路径的 counter
    coll = get_collector()
    keys = list(coll._counters[METRIC_HTTP_RESPONSE_TOTAL].keys())
    matches = [k for k in keys if dict(k).get("path") == path]
    assert matches == [], f"探测路径 {path} 不应计数，却有 {matches}"


# ============================================================
# 集成 · alerts.parse_prometheus_metrics 能读 5xx
# ============================================================


def test_parse_metrics_extracts_http_5xx_from_collector() -> None:
    # 直接 emit 一些 HTTP 计数
    emit_http_response(path="/v1/workflows/run", status_class="2xx")
    emit_http_response(path="/v1/workflows/run", status_class="2xx")
    emit_http_response(path="/v1/workflows/run", status_class="5xx")
    # 把 /metrics exposition 拉出来
    text = get_collector().render_prometheus()
    # 用 alerts 的 parser 解析
    parsed = parse_prometheus_metrics(text)
    assert parsed["http_5xx"] == 1
    assert parsed["http_total"] == 3


def test_parse_metrics_5xx_ratio_correct() -> None:
    """3 个 2xx + 1 个 5xx → 25% 5xx 率。"""
    for _ in range(3):
        emit_http_response(path="/x", status_class="2xx")
    emit_http_response(path="/x", status_class="5xx")
    text = get_collector().render_prometheus()
    parsed = parse_prometheus_metrics(text)
    ratio = parsed["http_5xx"] / parsed["http_total"] * 100
    assert ratio == pytest.approx(25.0)


def test_parse_metrics_handles_no_http_data() -> None:
    """没任何 HTTP emit → 0/0，告警 evaluator 不会崩。"""
    text = "otc_agent_node_total{node=\"x\",status=\"ok\"} 1\n"
    parsed = parse_prometheus_metrics(text)
    assert parsed["http_5xx"] == 0
    assert parsed["http_total"] == 0


# ============================================================
# 集成 · alerts.evaluate 触发 http_5xx_spike
# ============================================================


def test_evaluate_http_5xx_spike_fires_after_sustain() -> None:
    """5xx 率 ≥ 1% 持续 5 分钟 → P0 fire。"""
    from app.observability.alerts import AlertContext, AlertState, evaluate

    states: dict[str, AlertState] = {}

    # t=1000 snapshot only
    ctx0 = AlertContext(
        timestamp=1000.0, requests_total=0,
        metrics={"http_5xx": 0, "http_total": 0, "fallback_cascade_fail": 0,
                 "llm_error": 0, "llm_total": 0, "node_total": 0,
                 "canary_traffic_non_canary": 0, "p95_latency_ms": 0.0},
    )
    evaluate(ctx0, states)

    # t=1100 first breach: delta(5xx)=20, delta(total)=100 → 20% ≥ 1%
    ctx1 = AlertContext(
        timestamp=1100.0, requests_total=0,
        metrics={"http_5xx": 20, "http_total": 100, "fallback_cascade_fail": 0,
                 "llm_error": 0, "llm_total": 0, "node_total": 0,
                 "canary_traffic_non_canary": 0, "p95_latency_ms": 0.0},
    )
    out = evaluate(ctx1, states)
    # first_breach_at 刚设，sustain=0 < 300 → 不 fire
    fires = [o for o in out if o[0].name == "http_5xx_spike" and o[2] == "fire"]
    assert fires == []

    # t=1500 sustain=400 ≥ 300 → fire
    ctx2 = AlertContext(
        timestamp=1500.0, requests_total=0,
        metrics={"http_5xx": 40, "http_total": 200, "fallback_cascade_fail": 0,
                 "llm_error": 0, "llm_total": 0, "node_total": 0,
                 "canary_traffic_non_canary": 0, "p95_latency_ms": 0.0},
    )
    out = evaluate(ctx2, states)
    fires = [o for o in out if o[0].name == "http_5xx_spike" and o[2] == "fire"]
    assert len(fires) == 1, f"应触发 http_5xx_spike P0；实得 {fires}"
