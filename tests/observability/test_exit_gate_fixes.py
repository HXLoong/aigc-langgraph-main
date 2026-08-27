"""#157 裁决落地：告警与 M4 退出门测量修复（ADR 0017/0019）。

1. cascade fail 率分母改为总请求数（http_total），不再用 node_total（宽 6-8 倍）
2. P95 直方图剔除节点级样本（带 node= label），只统计端到端请求样本
3. /v1/workflows/run 出口接线 emit_intent_latency（端到端 P95 数据源）
4. canary_status：ALL 全量模式 + dry_run_intercept > 0 → 违规（runbook §5 护栏成真）
"""
from __future__ import annotations

from app.observability.alerts import (
    AlertContext,
    AlertState,
    _evaluate_metric,
    parse_prometheus_metrics,
)
from scripts.canary_status import CanaryStatus, _parse_dry_run_intercept


def _ctx(metrics: dict) -> AlertContext:
    return AlertContext(timestamp=2000.0, metrics=metrics, requests_total=int(metrics.get('http_total', 0)))


def _state(metrics: dict) -> AlertState:
    return AlertState(name="cascade_fail_high", last_timestamp=1000.0, last_metrics=metrics)


class TestCascadeDenominator:
    def test_cascade_rate_uses_http_total(self) -> None:
        """5 次 cascade / 100 请求（700 节点执行）= 5%，不是 0.71%。"""
        state = _state({"fallback_cascade_fail": 0, "http_total": 0, "node_total": 0})
        ctx = _ctx({"fallback_cascade_fail": 5, "http_total": 100, "node_total": 700})
        assert _evaluate_metric("cascade_fail_high", ctx, state) == 5.0


class TestP95ExcludesNodeSamples:
    def test_node_labeled_buckets_ignored(self) -> None:
        """带 node= label 的桶（emit_node_completed 写入）不进 P95。"""
        text = """
otc_agent_intent_latency_ms_bucket{product_type="unknown",intent="unknown",node="ingest",le="100"} 50
otc_agent_intent_latency_ms_bucket{product_type="unknown",intent="unknown",node="ingest",le="+Inf"} 50
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order_request",le="5000"} 10
otc_agent_intent_latency_ms_bucket{product_type="swap",intent="place_order_request",le="+Inf"} 10
"""
        result = parse_prometheus_metrics(text)
        # 只剩端到端样本（10 条全落在 le=5000 桶内）→ P95 ≤ 5000
        assert 0 < result["p95_latency_ms"] <= 5000

    def test_request_level_buckets_counted(self) -> None:
        text = """
otc_agent_intent_latency_ms_bucket{product_type="option",intent="new_inquiry",le="1000"} 95
otc_agent_intent_latency_ms_bucket{product_type="option",intent="new_inquiry",le="20000"} 100
otc_agent_intent_latency_ms_bucket{product_type="option",intent="new_inquiry",le="+Inf"} 100
"""
        result = parse_prometheus_metrics(text)
        assert 1000 <= result["p95_latency_ms"] <= 20000


class TestCanaryDryRunGuard:
    def _status(self, allowlist: list[str], dry_run: int, non_canary: int = 0) -> CanaryStatus:
        return CanaryStatus(
            timestamp="t",
            metrics_url_host="h",
            allowlist=allowlist,
            mode="m",
            canary_count=10,
            non_canary_count=non_canary,
            dry_run_intercept=dry_run,
        )

    def test_all_mode_with_dry_run_intercept_is_breach(self) -> None:
        """runbook §5：CANARY_ROOM_IDS=ALL（全量）+ dry_run 拦截 > 0 = 配置错误 P0。"""
        assert self._status(["ALL"], dry_run=3).is_breach is True

    def test_all_mode_without_dry_run_ok(self) -> None:
        assert self._status(["ALL"], dry_run=0).is_breach is False

    def test_partial_mode_non_canary_still_breach(self) -> None:
        assert self._status(["r-1"], dry_run=0, non_canary=2).is_breach is True

    def test_parse_dry_run_counter(self) -> None:
        text = """
otc_agent_dry_run_intercept_total{client="swap",operation="operate"} 2
otc_agent_dry_run_intercept_total{client="option",operation="operate"} 1
otc_agent_canary_traffic_total{is_canary="true"} 5
"""
        assert _parse_dry_run_intercept(text) == 3
