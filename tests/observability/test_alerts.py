"""C1.6 告警评估器单元测试（Issue #55）。"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.observability.alerts import (
    AlertContext,
    AlertState,
    THRESHOLDS,
    _calc_ratio_pct,
    evaluate,
    format_alert_message,
    load_state,
    parse_prometheus_metrics,
    save_state,
)


def test_calc_ratio_pct_handles_zero_denominator() -> None:
    assert _calc_ratio_pct(5, 0) == 0.0
    assert _calc_ratio_pct(0, 100) == 0.0
    assert _calc_ratio_pct(5, 100) == 5.0


def test_thresholds_align_with_adr_0017() -> None:
    """ADR 0017 量化阈值断言。"""
    assert THRESHOLDS["http_5xx_spike"].threshold_pct == 1.0
    assert THRESHOLDS["http_5xx_spike"].sustain_seconds == 300
    assert THRESHOLDS["http_5xx_spike"].severity == "P0"

    assert THRESHOLDS["cascade_fail_high"].threshold_pct == 5.0
    assert THRESHOLDS["cascade_fail_high"].sustain_seconds == 600

    assert THRESHOLDS["llm_failure_high"].threshold_pct == 10.0
    assert THRESHOLDS["llm_failure_high"].sustain_seconds == 300


def test_parse_prometheus_metrics_cascade_fail() -> None:
    text = """
# TYPE otc_agent_fallback_total counter
otc_agent_fallback_total{reason="cascade_fail"} 5
otc_agent_fallback_total{reason="zero_match"} 3
otc_agent_fallback_total{reason="hitl_card"} 2
"""
    result = parse_prometheus_metrics(text)
    assert result["fallback_cascade_fail"] == 5


def test_parse_prometheus_metrics_llm_total() -> None:
    text = """
# TYPE otc_agent_llm_total counter
otc_agent_llm_total{model="qwen3-30b-a3b",status="ok"} 90
otc_agent_llm_total{model="qwen3-30b-a3b",status="error"} 5
otc_agent_llm_total{model="qwen3-30b-a3b",status="timeout"} 5
"""
    result = parse_prometheus_metrics(text)
    assert result["llm_total"] == 100
    assert result["llm_error"] == 10  # error + timeout


def test_parse_prometheus_metrics_node_total() -> None:
    text = """
otc_agent_node_total{node="swap.intent",status="ok"} 100
otc_agent_node_total{node="swap.intent",status="error"} 2
otc_agent_node_total{node="render",status="ok"} 102
"""
    result = parse_prometheus_metrics(text)
    assert result["node_total"] == 204


def test_evaluate_no_breach_no_fire() -> None:
    """5xx 率 0.5% < 1% 阈值，不应触发。"""
    ctx = AlertContext(
        timestamp=1000.0,
        requests_total=1000,
        metrics={"http_5xx": 5},  # 5/1000 = 0.5%
    )
    states: dict[str, AlertState] = {}
    transitions = evaluate(ctx, states)
    assert transitions == []


def test_evaluate_breach_starts_sustain_clock() -> None:
    """首次越线只启动计时器，不立即触发。"""
    ctx = AlertContext(
        timestamp=1000.0,
        requests_total=1000,
        metrics={"fallback_cascade_fail": 100},  # 10% ≥ 5%
    )
    states: dict[str, AlertState] = {}
    transitions = evaluate(ctx, states)
    # 第一次越线，开始计时但还未持续 600 秒
    assert transitions == []
    assert states["cascade_fail_high"].first_breach_at == 1000.0
    assert not states["cascade_fail_high"].is_firing


def test_evaluate_breach_sustained_fires() -> None:
    """越线持续 >= sustain_seconds 才触发。"""
    states = {
        "cascade_fail_high": AlertState(
            name="cascade_fail_high",
            first_breach_at=1000.0,
        )
    }
    # 第二次评估，时间过去 700 秒 > 600 秒阈值
    ctx = AlertContext(
        timestamp=1700.0,
        requests_total=1000,
        metrics={"fallback_cascade_fail": 100},
    )
    transitions = evaluate(ctx, states)
    assert len(transitions) == 1
    threshold, state, kind = transitions[0]
    assert threshold.name == "cascade_fail_high"
    assert kind == "fire"
    assert state.is_firing


def test_evaluate_recovery_signals() -> None:
    """从 firing → 不越线 → 发 recovery 信号。"""
    states = {
        "cascade_fail_high": AlertState(
            name="cascade_fail_high",
            is_firing=True,
            first_breach_at=1000.0,
            fired_at=1700.0,
        )
    }
    ctx = AlertContext(
        timestamp=2000.0,
        requests_total=1000,
        metrics={"fallback_cascade_fail": 1},  # 0.1% < 5%
    )
    transitions = evaluate(ctx, states)
    assert len(transitions) == 1
    threshold, state, kind = transitions[0]
    assert kind == "recover"
    assert not state.is_firing
    assert state.first_breach_at == 0.0


def test_evaluate_no_double_fire() -> None:
    """已 firing 状态下持续越线不重复发告警。"""
    states = {
        "cascade_fail_high": AlertState(
            name="cascade_fail_high",
            is_firing=True,
            first_breach_at=1000.0,
            fired_at=1700.0,
        )
    }
    ctx = AlertContext(
        timestamp=1900.0,
        requests_total=1000,
        metrics={"fallback_cascade_fail": 100},
    )
    transitions = evaluate(ctx, states)
    assert transitions == []


def test_save_and_load_state_roundtrip(tmp_path) -> None:
    """状态文件读写一致。"""
    state_file = tmp_path / "alert_state.json"
    with patch.dict("os.environ", {"ALERT_STATE_FILE": str(state_file)}):
        states = {
            "cascade_fail_high": AlertState(
                name="cascade_fail_high",
                is_firing=True,
                first_breach_at=1000.0,
                fired_at=1700.0,
            )
        }
        save_state(states)
        loaded = load_state()
        assert "cascade_fail_high" in loaded
        assert loaded["cascade_fail_high"].is_firing is True
        assert loaded["cascade_fail_high"].first_breach_at == 1000.0


def test_load_state_missing_file_returns_empty(tmp_path) -> None:
    """文件不存在时返回空 dict（首次启动）。"""
    state_file = tmp_path / "non_existent.json"
    with patch.dict("os.environ", {"ALERT_STATE_FILE": str(state_file)}):
        assert load_state() == {}


def test_load_state_corrupt_file_returns_empty(tmp_path) -> None:
    """坏文件不应崩，返回空 dict。"""
    state_file = tmp_path / "corrupt.json"
    state_file.write_text("not json {", encoding="utf-8")
    with patch.dict("os.environ", {"ALERT_STATE_FILE": str(state_file)}):
        assert load_state() == {}


def test_format_alert_message_fire() -> None:
    ctx = AlertContext(timestamp=1700.0, requests_total=1000, metrics={})
    msg = format_alert_message(THRESHOLDS["cascade_fail_high"], "fire", ctx)
    assert "触发" in msg
    assert "P1" in msg
    assert "cascade_fail_high" in msg
    assert "5%" in msg


def test_format_alert_message_recover() -> None:
    ctx = AlertContext(timestamp=2000.0, requests_total=1000, metrics={})
    msg = format_alert_message(THRESHOLDS["cascade_fail_high"], "recover", ctx)
    assert "恢复" in msg
    assert "✅" in msg
