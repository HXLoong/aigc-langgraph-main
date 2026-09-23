"""alerts.py · P95 延迟告警测试（ADR 0019 P1）。

测试范围：
- _extract_le 标签提取
- _histogram_quantile_ms 算法（含 +Inf 回退、空桶、单桶）
- parse_prometheus_metrics 集成 P95
- evaluate P95 触发 / 持续 / 恢复 / 与现有 ratio 告警共存
"""
from __future__ import annotations

import math

from app.observability.alerts import (
    THRESHOLDS,
    AlertContext,
    AlertState,
    _extract_le,
    _histogram_quantile_ms,
    evaluate,
    parse_prometheus_metrics,
)

# ============================================================
# _extract_le
# ============================================================


def test_extract_le_basic() -> None:
    assert _extract_le('le="500"') == 500.0


def test_extract_le_among_other_labels() -> None:
    assert _extract_le('product_type="swap",intent="place_order",le="2000"') == 2000.0


def test_extract_le_inf() -> None:
    r = _extract_le('le="+Inf"')
    assert r is not None and math.isinf(r)


def test_extract_le_missing_returns_none() -> None:
    assert _extract_le('product_type="swap"') is None


def test_extract_le_malformed_returns_none() -> None:
    assert _extract_le('le="not-a-number"') is None


# ============================================================
# _histogram_quantile_ms · 算法
# ============================================================


def test_quantile_empty_returns_zero() -> None:
    assert _histogram_quantile_ms({}, 0.95) == 0.0


def test_quantile_zero_total_returns_zero() -> None:
    """所有 bucket count 都是 0 → 总数 0 → 返回 0。"""
    assert _histogram_quantile_ms({100.0: 0, 500.0: 0, float("inf"): 0}, 0.95) == 0.0


def test_quantile_single_bucket_returns_le() -> None:
    """所有观测落在 100ms 桶 → P95 = 100ms。"""
    buckets = {100.0: 10, 500.0: 10, float("inf"): 10}
    assert _histogram_quantile_ms(buckets, 0.95) == 100.0


def test_quantile_p95_falls_in_500_bucket() -> None:
    """100ms: 5 / 500ms: 19 / 1000ms: 20 → total=20, target=19, 500ms 包含 19 → P95=500ms。"""
    buckets = {100.0: 5, 500.0: 19, 1000.0: 20, float("inf"): 20}
    assert _histogram_quantile_ms(buckets, 0.95) == 500.0


def test_quantile_p50_finds_middle() -> None:
    buckets = {100.0: 3, 500.0: 11, 1000.0: 20, float("inf"): 20}
    # total=20, target=10 → 第一个 ≥ 10 的桶是 500（cumulative=11）
    assert _histogram_quantile_ms(buckets, 0.5) == 500.0


def test_quantile_inf_falls_back_to_last_finite() -> None:
    """如果 P95 命中 +Inf 桶，回退到最后一个有限桶（避免 inf 拉爆告警）。"""
    buckets = {100.0: 1, 500.0: 1, 1000.0: 1, float("inf"): 100}
    # total=100, target=95，前 3 桶都是 1 < 95，只有 inf 含 100 ≥ 95
    # 回退到 1000
    assert _histogram_quantile_ms(buckets, 0.95) == 1000.0


def test_quantile_inf_only_returns_zero() -> None:
    """只有 inf 桶 → 没有有限桶可回退 → 0.0。"""
    buckets = {float("inf"): 50}
    assert _histogram_quantile_ms(buckets, 0.95) == 0.0


# ============================================================
# parse_prometheus_metrics · 集成 P95
# ============================================================


def test_parse_extracts_p95_from_histogram() -> None:
    text = """\
# TYPE otc_agent_intent_latency_ms histogram
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="100"} 5
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="500"} 19
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="1000"} 20
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="+Inf"} 20
otc_agent_intent_latency_ms_sum{product_type="swap",intent="place_order"} 4500
otc_agent_intent_latency_ms_count{product_type="swap",intent="place_order"} 20
"""
    result = parse_prometheus_metrics(text)
    assert result["p95_latency_ms"] == 500.0


def test_parse_aggregates_p95_across_labels() -> None:
    """跨多个 (product_type, intent) label 聚合后算 P95。"""
    text = """\
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="100"} 5
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="500"} 10
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order",le="+Inf"} 10
otc_agent_intent_latency_ms_bucket{product_type="option",intent="inquiry",le="100"} 0
otc_agent_intent_latency_ms_bucket{product_type="option",intent="inquiry",le="500"} 5
otc_agent_intent_latency_ms_bucket{product_type="option",intent="inquiry",le="2000"} 10
otc_agent_intent_latency_ms_bucket{product_type="option",intent="inquiry",le="+Inf"} 10
"""
    result = parse_prometheus_metrics(text)
    # 跨 label 累积：le=100 → 5+0=5, le=500 → 10+5=15, le=2000 → 10+10=20 (le=500 不在 option)
    # 实际：le=100: 5, le=500: 15, le=2000: 20 (来自 option), le=+Inf: 20
    # total=20, target=19 → 第一个 ≥19 的是 le=2000（cumulative=20）
    assert result["p95_latency_ms"] == 2000.0


def test_parse_handles_no_histogram_gracefully() -> None:
    """完全没有 latency histogram → p95_latency_ms = 0.0（不抛）。"""
    text = "otc_agent_node_total{node=\"ingest\",status=\"ok\"} 10\n"
    result = parse_prometheus_metrics(text)
    assert result["p95_latency_ms"] == 0.0


# ============================================================
# THRESHOLDS · 配置
# ============================================================


def test_p95_threshold_present_and_p1() -> None:
    assert "p95_latency_degraded" in THRESHOLDS
    t = THRESHOLDS["p95_latency_degraded"]
    assert t.severity == "P1"
    assert t.kind == "absolute"
    assert t.sustain_seconds == 600  # 10 分钟


def test_p95_threshold_value_matches_baseline_times_3() -> None:
    """当前模型 dry-run baseline 8554ms × 3 = 25662ms。"""
    t = THRESHOLDS["p95_latency_degraded"]
    assert t.threshold_value == 25662.0


def test_threshold_pct_property_aliases_threshold_value() -> None:
    """向后兼容：旧代码读 .threshold_pct 仍能取到 .threshold_value。"""
    t = THRESHOLDS["http_5xx_spike"]
    assert t.threshold_pct == t.threshold_value == 1.0


# ============================================================
# evaluate · P95 状态机
# ============================================================


def _make_ctx(timestamp: float, p95: float = 0.0, **metrics) -> AlertContext:
    base = {"http_5xx": 0, "fallback_cascade_fail": 0, "llm_error": 0,
            "llm_total": 0, "node_total": 0, "canary_traffic_non_canary": 0,
            "p95_latency_ms": p95}
    base.update(metrics)
    return AlertContext(timestamp=timestamp, requests_total=0, metrics=base)


def test_p95_below_threshold_does_not_fire() -> None:
    states: dict[str, AlertState] = {}
    # 首次评估只记 snapshot
    evaluate(_make_ctx(1000.0, p95=4000.0), states)
    # 第二次评估，P95 4500ms 低于阈值 → 不 fire
    out = evaluate(_make_ctx(1060.0, p95=4500.0), states)
    p95_fires = [o for o in out if o[0].name == "p95_latency_degraded"]
    assert p95_fires == []


def test_p95_above_threshold_fires_after_sustain() -> None:
    states: dict[str, AlertState] = {}
    # 首次评估（不触发，只记 snapshot）
    evaluate(_make_ctx(1000.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2), states)
    # 第二次：P95 超过阈值，但持续才 60s < 600s sustain → 不 fire
    out = evaluate(_make_ctx(1060.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2), states)
    p95_fires = [o for o in out if o[0].name == "p95_latency_degraded" and o[2] == "fire"]
    assert p95_fires == []

    # 推进到 10 分钟后，持续越线 → fire
    out = evaluate(_make_ctx(1660.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2), states)
    p95_fires = [o for o in out if o[0].name == "p95_latency_degraded" and o[2] == "fire"]
    assert len(p95_fires) == 1


def test_p95_recovery_when_drops_below_threshold() -> None:
    states: dict[str, AlertState] = {}
    # t=1000 snapshot only（last_ts=0）
    evaluate(_make_ctx(1000.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2), states)
    # t=1700 first breach → first_breach_at=1700, sustain=0 不 fire
    evaluate(_make_ctx(1700.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2), states)
    # t=2400 sustain=700 ≥ 600 → fire
    evaluate(_make_ctx(2400.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2), states)
    state = states["p95_latency_degraded"]
    assert state.is_firing, "前置条件：P95 已 firing"

    # 现在 P95 降回 4000ms → 应触发 recover
    out = evaluate(_make_ctx(2700.0, p95=4000.0), states)
    recovers = [o for o in out if o[0].name == "p95_latency_degraded" and o[2] == "recover"]
    assert len(recovers) == 1
    assert not states["p95_latency_degraded"].is_firing


def test_p95_does_not_interfere_with_ratio_alerts() -> None:
    """P95 用 absolute 路径，其他用 ratio 路径，两者并存不串台。

    LLM sustain=300s, P95 sustain=600s。需要两次 evaluate 让 first_breach_at
    起算后，再推进到各自 sustain 之后才会 fire。
    """
    states: dict[str, AlertState] = {}
    # t=1000 snapshot only
    evaluate(_make_ctx(1000.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2, llm_total=100, llm_error=20), states)
    # t=1400 first breach for both（first_breach_at=1400）, sustain=0
    evaluate(_make_ctx(1400.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2,
                       llm_total=200, llm_error=40), states)
    # t=2100：
    #   - P95 sustain = 2100-1400 = 700 ≥ 600 → fire
    #   - LLM sustain = 700 ≥ 300 → fire；delta rate = (60-40)/(300-200)=20% > 10%
    out = evaluate(_make_ctx(2100.0, p95=THRESHOLDS["p95_latency_degraded"].threshold_value * 1.2,
                              llm_total=300, llm_error=60), states)
    fires = {o[0].name for o in out if o[2] == "fire"}
    assert "p95_latency_degraded" in fires
    assert "llm_failure_high" in fires


def test_p95_threshold_via_env_override(monkeypatch) -> None:
    """M2_BASELINE_P95_MS env 可调整阈值（运维场景，无需改代码）。"""
    monkeypatch.setenv("M2_BASELINE_P95_MS", "1000")
    # 必须 reload 模块才能重新读 env（模块级常量）
    import importlib

    from app.observability import alerts as alerts_mod
    importlib.reload(alerts_mod)
    try:
        # baseline=1000 × 3 = 3000
        assert alerts_mod.THRESHOLDS["p95_latency_degraded"].threshold_value == 3000.0
    finally:
        # 还原默认值避免污染其他测试
        monkeypatch.delenv("M2_BASELINE_P95_MS", raising=False)
        importlib.reload(alerts_mod)
