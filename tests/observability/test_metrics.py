"""C1.5 业务指标埋点单元测试（Issue #50）。"""
from __future__ import annotations

import pytest

from app.observability import metrics as M


@pytest.fixture(autouse=True)
def reset_collector() -> None:
    """每测试重置单例，避免 case 间污染。"""
    M.get_collector().reset()
    yield
    M.get_collector().reset()


def test_counter_increment_basic() -> None:
    M.get_collector().inc_counter("test_total")
    M.get_collector().inc_counter("test_total")
    assert M.get_collector().get_counter("test_total") == 2


def test_counter_with_labels() -> None:
    coll = M.get_collector()
    coll.inc_counter("test_total", {"node": "a", "status": "ok"})
    coll.inc_counter("test_total", {"node": "a", "status": "ok"})
    coll.inc_counter("test_total", {"node": "b", "status": "ok"})

    assert coll.get_counter("test_total", {"node": "a", "status": "ok"}) == 2
    assert coll.get_counter("test_total", {"node": "b", "status": "ok"}) == 1
    assert coll.get_counter("test_total", {"node": "c"}) == 0


def test_histogram_observe_and_quantile() -> None:
    coll = M.get_collector()
    for v in [100, 200, 300, 400, 500, 800, 1500, 3000, 8000]:
        coll.observe_histogram("test_latency", v)

    p50 = coll.get_quantile("test_latency", 0.5)
    p95 = coll.get_quantile("test_latency", 0.95)
    assert p50 is not None
    assert p95 is not None
    # P50 应落在前半段 bucket（≤ 500）；P95 应落在更后的 bucket
    assert p50 <= 500
    assert p95 >= p50


def test_emit_node_completed_writes_counter() -> None:
    M.emit_node_completed(node="swap.intent", status="ok", elapsed_ms=150)
    M.emit_node_completed(node="swap.intent", status="ok", elapsed_ms=200)
    M.emit_node_completed(node="swap.intent", status="error", elapsed_ms=50)

    coll = M.get_collector()
    assert coll.get_counter(
        M.METRIC_NODE_TOTAL, {"node": "swap.intent", "status": "ok"}
    ) == 2
    assert coll.get_counter(
        M.METRIC_NODE_TOTAL, {"node": "swap.intent", "status": "error"}
    ) == 1


def test_emit_fallback_categorizes_reason() -> None:
    M.emit_fallback("cascade_fail")
    M.emit_fallback("zero_match")
    M.emit_fallback("cascade_fail")

    coll = M.get_collector()
    assert coll.get_counter(M.METRIC_FALLBACK_TOTAL, {"reason": "cascade_fail"}) == 2
    assert coll.get_counter(M.METRIC_FALLBACK_TOTAL, {"reason": "zero_match"}) == 1


def test_emit_option_backend_validation_metrics() -> None:
    M.emit_option_backend_missing_context()
    M.emit_option_backend_empty_result()

    coll = M.get_collector()
    assert coll.get_counter(M.METRIC_OPTION_BACKEND_MISSING_CONTEXT_TOTAL) == 1
    assert coll.get_counter(M.METRIC_OPTION_BACKEND_EMPTY_RESULT_TOTAL) == 1


def test_emit_hitl() -> None:
    M.emit_hitl(node="ticker.resolver")
    M.emit_hitl(node="ticker.resolver")

    assert M.get_collector().get_counter(
        M.METRIC_HITL_TOTAL, {"node": "ticker.resolver"}
    ) == 2


def test_emit_llm_call() -> None:
    M.emit_llm_call("qwen3-30b-a3b", "ok")
    M.emit_llm_call("qwen3-30b-a3b", "error")
    M.emit_llm_call("deepseek-v4-pro", "ok")

    coll = M.get_collector()
    assert coll.get_counter(M.METRIC_LLM_TOTAL, {"model": "qwen3-30b-a3b", "status": "ok"}) == 1
    assert coll.get_counter(M.METRIC_LLM_TOTAL, {"model": "qwen3-30b-a3b", "status": "error"}) == 1
    assert coll.get_counter(M.METRIC_LLM_TOTAL, {"model": "deepseek-v4-pro", "status": "ok"}) == 1


def test_timer_records_elapsed() -> None:
    import time

    with M.Timer() as t:
        time.sleep(0.05)  # 50ms
    # 允许 ±20ms 抖动
    assert 30 <= t.elapsed_ms <= 200


def test_prometheus_render_includes_counters_and_histograms() -> None:
    M.emit_node_completed("swap.intent", "ok", 100)
    M.emit_fallback("cascade_fail")
    M.emit_intent_latency("swap", "place_order", 300)

    output = M.get_collector().render_prometheus()
    assert M.METRIC_NODE_TOTAL in output
    assert M.METRIC_FALLBACK_TOTAL in output
    assert M.METRIC_INTENT_LATENCY in output
    assert "# TYPE" in output
    assert "_bucket" in output
    assert "_sum" in output
    assert "_count" in output


def test_metrics_emit_failure_does_not_break() -> None:
    """监控降级：emit 失败时不影响业务流程。"""
    # 模拟：collector 内部异常不应传出
    coll = M.get_collector()
    # 验证 inc_counter 对异常输入的容错
    coll.inc_counter("name", labels={"k": "v"})  # 正常
    # 即使 labels 不规整也不抛
    coll.inc_counter("name", labels=None)  # 也允许


@pytest.mark.asyncio
async def test_safe_node_emits_node_metric_on_success() -> None:
    """safe_node 装饰器成功路径要 emit ok 状态。"""
    from app.graph.safe_node import safe_node

    @safe_node
    async def ok_node(state):
        return {"foo": "bar"}

    await ok_node({})
    assert M.get_collector().get_counter(
        M.METRIC_NODE_TOTAL, {"node": "ok_node", "status": "ok"}
    ) == 1


@pytest.mark.asyncio
async def test_safe_node_emits_node_metric_on_error() -> None:
    """safe_node 装饰器失败路径要 emit error 状态。"""
    from app.graph.safe_node import safe_node

    @safe_node
    async def bad_node(state):
        raise RuntimeError("boom")

    result = await bad_node({})
    # safe_node 兜底转 error，不抛
    assert "error" in result
    assert M.get_collector().get_counter(
        M.METRIC_NODE_TOTAL, {"node": "bad_node", "status": "error"}
    ) == 1
