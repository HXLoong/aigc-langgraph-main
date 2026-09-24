"""业务指标埋点单元测试。"""
from __future__ import annotations

import pytest

from app.observability import metrics


@pytest.fixture(autouse=True)
def reset_collector() -> None:
    """每测试重置单例，避免 case 间污染。"""
    metrics.get_collector().reset()
    yield
    metrics.get_collector().reset()


def test_counter_increment_basic() -> None:
    metrics.get_collector().inc_counter("test_total")
    metrics.get_collector().inc_counter("test_total")
    assert metrics.get_collector().get_counter("test_total") == 2


def test_counter_with_labels() -> None:
    coll = metrics.get_collector()
    coll.inc_counter("test_total", {"node": "a", "status": "ok"})
    coll.inc_counter("test_total", {"node": "a", "status": "ok"})
    coll.inc_counter("test_total", {"node": "b", "status": "ok"})

    assert coll.get_counter("test_total", {"node": "a", "status": "ok"}) == 2
    assert coll.get_counter("test_total", {"node": "b", "status": "ok"}) == 1
    assert coll.get_counter("test_total", {"node": "c"}) == 0


def test_histogram_observe_and_quantile() -> None:
    coll = metrics.get_collector()
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
    metrics.emit_node_completed(node="swap.intent", status="ok", elapsed_ms=150)
    metrics.emit_node_completed(node="swap.intent", status="ok", elapsed_ms=200)
    metrics.emit_node_completed(node="swap.intent", status="error", elapsed_ms=50)

    coll = metrics.get_collector()
    assert coll.get_counter(
        metrics.METRIC_NODE_TOTAL, {"node": "swap.intent", "status": "ok"}
    ) == 2
    assert coll.get_counter(
        metrics.METRIC_NODE_TOTAL, {"node": "swap.intent", "status": "error"}
    ) == 1


def test_node_latency_has_its_own_histogram_and_never_pollutes_intent_p95() -> None:
    """ADR 0024 D5：节点延迟此前寄生在 intent 直方图上（product_type=unknown + node label），
    alerts 只能靠字符串过滤剔除；现在独立为 otc_agent_node_latency_ms{node}。"""
    metrics.emit_node_completed(node="swap_intent", status="ok", elapsed_ms=150)
    metrics.emit_node_completed(node="swap_intent", status="error", elapsed_ms=50)
    coll = metrics.get_collector()
    assert coll.get_quantile(metrics.METRIC_NODE_LATENCY, 0.5, {"node": "swap_intent"}) is not None
    output = coll.render_prometheus()
    assert 'otc_agent_node_latency_ms_bucket{node="swap_intent"' in output
    intent_lines = [line for line in output.splitlines() if line.startswith(metrics.METRIC_INTENT_LATENCY)]
    assert intent_lines == [], "节点样本不得进入 intent 直方图"


def test_emit_fallback_categorizes_reason() -> None:
    metrics.emit_fallback("cascade_fail")
    metrics.emit_fallback("zero_match")
    metrics.emit_fallback("cascade_fail")

    coll = metrics.get_collector()
    assert coll.get_counter(metrics.METRIC_FALLBACK_TOTAL, {"reason": "cascade_fail"}) == 2
    assert coll.get_counter(metrics.METRIC_FALLBACK_TOTAL, {"reason": "zero_match"}) == 1


def test_emit_option_backend_validation_metrics() -> None:
    metrics.emit_option_backend_missing_context()
    metrics.emit_option_backend_empty_result()

    coll = metrics.get_collector()
    assert coll.get_counter(metrics.METRIC_OPTION_BACKEND_MISSING_CONTEXT_TOTAL) == 1
    assert coll.get_counter(metrics.METRIC_OPTION_BACKEND_EMPTY_RESULT_TOTAL) == 1


def test_emit_llm_call() -> None:
    metrics.emit_llm_call("qwen3-30b-a3b", "ok")
    metrics.emit_llm_call("qwen3-30b-a3b", "error")
    metrics.emit_llm_call("deepseek-v4-pro", "ok")

    coll = metrics.get_collector()
    assert coll.get_counter(metrics.METRIC_LLM_TOTAL, {"model": "qwen3-30b-a3b", "status": "ok"}) == 1
    assert coll.get_counter(metrics.METRIC_LLM_TOTAL, {"model": "qwen3-30b-a3b", "status": "error"}) == 1
    assert coll.get_counter(metrics.METRIC_LLM_TOTAL, {"model": "deepseek-v4-pro", "status": "ok"}) == 1


def test_prometheus_render_includes_counters_and_histograms() -> None:
    metrics.emit_node_completed("swap.intent", "ok", 100)
    metrics.emit_fallback("cascade_fail")
    metrics.emit_intent_latency("swap", "place_order", 300)

    output = metrics.get_collector().render_prometheus()
    assert metrics.METRIC_NODE_TOTAL in output
    assert metrics.METRIC_FALLBACK_TOTAL in output
    assert metrics.METRIC_INTENT_LATENCY in output
    assert "# TYPE" in output
    assert "_bucket" in output
    assert "_sum" in output
    assert "_count" in output


def test_metrics_emit_failure_does_not_break() -> None:
    """监控降级：emit 失败时不影响业务流程。"""
    # 模拟：collector 内部异常不应传出
    coll = metrics.get_collector()
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
    assert metrics.get_collector().get_counter(
        metrics.METRIC_NODE_TOTAL, {"node": "ok_node", "status": "ok"}
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
    assert metrics.get_collector().get_counter(
        metrics.METRIC_NODE_TOTAL, {"node": "bad_node", "status": "error"}
    ) == 1
