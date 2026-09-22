"""scripts/metrics_snapshot.py · 解析器 + 渲染单元测试。"""
from __future__ import annotations

from scripts.metrics_snapshot import (
    MetricsSnapshot,
    _parse_labels,
    _parse_metrics,
    _sum_by_label,
    render_human,
    render_json,
)

# ============================================================
# _parse_labels
# ============================================================


def test_parse_labels_single() -> None:
    assert _parse_labels('is_canary="true"') == (("is_canary", "true"),)


def test_parse_labels_multi_sorted() -> None:
    """多 label 应按 key 字母序输出 tuple（保证查找稳定）。"""
    result = _parse_labels('target="mysql",status="ok"')
    assert result == (("status", "ok"), ("target", "mysql"))


def test_parse_labels_empty_string() -> None:
    assert _parse_labels("") == ()


def test_parse_labels_quoted_values_stripped() -> None:
    assert _parse_labels('node="ingest"') == (("node", "ingest"),)


# ============================================================
# _parse_metrics
# ============================================================


def test_parse_simple_counter_with_labels() -> None:
    text = """
# HELP otc_agent_node_total ...
# TYPE otc_agent_node_total counter
otc_agent_node_total{node="ingest",status="ok"} 142
otc_agent_node_total{node="ingest",status="error"} 0
"""
    parsed = _parse_metrics(text)
    assert "otc_agent_node_total" in parsed
    ingest_ok = (("node", "ingest"), ("status", "ok"))
    assert parsed["otc_agent_node_total"][ingest_ok] == 142.0


def test_parse_skips_histogram_derived_metrics() -> None:
    """_bucket / _sum / _count 不进 snapshot（直方图衍生指标不在 F4 决策范围）。"""
    text = """
otc_agent_intent_latency_ms_bucket{le="100"} 50
otc_agent_intent_latency_ms_sum 12345
otc_agent_intent_latency_ms_count 100
"""
    parsed = _parse_metrics(text)
    assert "otc_agent_intent_latency_ms_bucket" not in parsed
    assert "otc_agent_intent_latency_ms_sum" not in parsed
    assert "otc_agent_intent_latency_ms_count" not in parsed


def test_parse_handles_no_label_counter() -> None:
    """无 label 的 counter 也能解析。"""
    text = "some_counter 42\n"
    parsed = _parse_metrics(text)
    assert parsed["some_counter"][()] == 42.0


def test_parse_ignores_malformed_lines() -> None:
    """损坏行不让整个解析崩。"""
    text = """
otc_agent_node_total{node="ingest",status="ok"} 5
otc_agent_node_total{broken_line
otc_agent_node_total{node="render",status="ok"} 3
"""
    parsed = _parse_metrics(text)
    assert len(parsed["otc_agent_node_total"]) == 2


def test_parse_empty_text() -> None:
    assert _parse_metrics("") == {}


# ============================================================
# _sum_by_label
# ============================================================


def test_sum_by_label_basic() -> None:
    counter = {
        (("node", "ingest"), ("status", "ok")): 10.0,
        (("node", "render"), ("status", "ok")): 5.0,
        (("node", "ingest"), ("status", "error")): 2.0,
    }
    assert _sum_by_label(counter, "status") == {"ok": 15.0, "error": 2.0}
    assert _sum_by_label(counter, "node") == {"ingest": 12.0, "render": 5.0}


def test_sum_by_label_missing_label() -> None:
    counter = {(("foo", "bar"),): 10.0}
    assert _sum_by_label(counter, "nonexistent") == {}


# ============================================================
# render_human · F4 关键场景断言
# ============================================================


def _make_snap(counters: dict) -> MetricsSnapshot:
    return MetricsSnapshot(
        timestamp="2026-05-12 11:50:00",
        host="prod-host",
        counters=counters,
    )


def test_render_canary_breach_alert() -> None:
    """非 canary 流量 > 0 → 输出含 ❌ 误切告警。"""
    snap = _make_snap({
        "otc_agent_canary_traffic_total": {
            (("is_canary", "true"),): 100.0,
            (("is_canary", "false"),): 3.0,
        }
    })
    text = render_human(snap)
    assert "❌ 误切告警！" in text
    assert "is_canary=false: 3" in text


def test_render_canary_clean() -> None:
    """非 canary 流量 = 0 → ✅"""
    snap = _make_snap({
        "otc_agent_canary_traffic_total": {(("is_canary", "true"),): 100.0}
    })
    text = render_human(snap)
    assert "✅" in text
    assert "❌" not in text


def test_render_llm_high_failure_rate_warning() -> None:
    """LLM 失败率 ≥ 10% → ⚠️ 标记。"""
    snap = _make_snap({
        "otc_agent_llm_total": {
            (("status", "ok"),): 80.0,
            (("status", "error"),): 20.0,  # 20% 失败率
        }
    })
    text = render_human(snap)
    assert "⚠️" in text
    assert "20.0% 失败率" in text


def test_render_node_error_rate_warning() -> None:
    """单节点错误率 ≥ 5% → ⚠️。"""
    snap = _make_snap({
        "otc_agent_node_total": {
            (("node", "intent_route"), ("status", "ok")): 90.0,
            (("node", "intent_route"), ("status", "error")): 10.0,  # 10%
        }
    })
    text = render_human(snap)
    assert "⚠️" in text


def test_render_health_check_fail() -> None:
    snap = _make_snap({
        "otc_agent_health_check_total": {
            (("status", "ok"), ("target", "mysql")): 60.0,
            (("status", "fail"), ("target", "java_backend")): 3.0,
            (("status", "ok"), ("target", "java_backend")): 57.0,
        }
    })
    text = render_human(snap)
    assert "❌" in text  # java_backend 有 fail
    assert "mysql" in text


def test_render_empty_snapshot() -> None:
    """空指标 snapshot 不崩。"""
    text = render_human(_make_snap({}))
    assert "无数据" in text
    assert "金丝雀未启用" in text


def test_render_json_machine_readable() -> None:
    """JSON 输出包含 timestamp + counters 列表化。"""
    import json as _json

    snap = _make_snap({
        "otc_agent_node_total": {
            (("node", "ingest"), ("status", "ok")): 5.0,
        }
    })
    text = render_json(snap)
    data = _json.loads(text)
    assert data["timestamp"] == "2026-05-12 11:50:00"
    assert "otc_agent_node_total" in data["counters"]
    assert data["counters"]["otc_agent_node_total"][0]["value"] == 5.0
    assert data["counters"]["otc_agent_node_total"][0]["labels"] == {
        "node": "ingest",
        "status": "ok",
    }


# ============================================================
# Fallback 业务指标场景
# ============================================================


def test_render_fallback_breakdown() -> None:
    snap = _make_snap({
        "otc_agent_fallback_total": {
            (("reason", "cascade_fail"),): 8.0,
            (("reason", "zero_match"),): 3.0,
            (("reason", "hitl_card"),): 1.0,
        }
    })
    text = render_human(snap)
    assert "Fallback 触发: 12" in text
    assert "cascade_fail:8" in text
