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


def _make_state_with_snapshot(
    name: str,
    last_metrics: dict[str, float],
    last_timestamp: float,
    is_firing: bool = False,
    first_breach_at: float = 0.0,
    fired_at: float = 0.0,
) -> AlertState:
    """构造一个有 last_metrics snapshot 的 state（非首次评估）。"""
    return AlertState(
        name=name,
        is_firing=is_firing,
        first_breach_at=first_breach_at,
        fired_at=fired_at,
        last_metrics=last_metrics,
        last_timestamp=last_timestamp,
    )


def test_evaluate_first_call_only_records_snapshot() -> None:
    """首次评估（last_timestamp=0）只记 snapshot 不触发告警，
    防止冷启动时拿累积值算率误报。"""
    ctx = AlertContext(
        timestamp=1000.0,
        requests_total=1000,
        # 即使累积值 99.9% cascade 也不该报（因还无历史 snapshot 算 delta）
        metrics={"node_total": 1000, "fallback_cascade_fail": 999},
    )
    states: dict[str, AlertState] = {}
    transitions = evaluate(ctx, states)
    assert transitions == []
    # snapshot 已记录供下次评估
    assert states["cascade_fail_high"].last_timestamp == 1000.0
    assert states["cascade_fail_high"].last_metrics["fallback_cascade_fail"] == 999


def test_evaluate_no_breach_when_delta_under_threshold() -> None:
    """delta 率 < 阈值不触发（5xx 0.5% < 1% 等价场景）。"""
    states = {
        "http_5xx_spike": _make_state_with_snapshot(
            name="http_5xx_spike",
            last_metrics={"node_total": 1000, "http_5xx": 5},
            last_timestamp=1000.0,
        )
    }
    # 新增 100 请求 / 0 5xx（短期 0% < 1%）
    ctx = AlertContext(
        timestamp=1060.0,
        requests_total=1100,
        metrics={"node_total": 1100, "http_5xx": 5},
    )
    transitions = evaluate(ctx, states)
    assert transitions == []


def test_evaluate_delta_detects_short_burst_not_diluted_by_history() -> None:
    """delta-based 计算的核心价值：长时间累积下短期 burst 仍能识别。

    旧累积算法 bug：app 跑 24h 后累积 1000 cascade / 100K 请求（1%），
    最近 1 分钟突发 30/50 cascade（60%）——按累积算只有 1.03% < 5% 阈值
    不触发。本测试断言新 delta 算法能识别 60% 突发。
    """
    states = {
        "cascade_fail_high": _make_state_with_snapshot(
            name="cascade_fail_high",
            # 上次评估：累积 100000 请求 / 1000 cascade（历史 1%）
            last_metrics={"node_total": 100000, "fallback_cascade_fail": 1000},
            last_timestamp=1000.0,
        )
    }
    # 本次评估：又来了 50 请求，其中 30 cascade（短期 60%）
    ctx = AlertContext(
        timestamp=1060.0,
        requests_total=100050,
        metrics={"node_total": 100050, "fallback_cascade_fail": 1030},
    )
    transitions = evaluate(ctx, states)
    # 60% 越线 → 启动计时器（still 未持续 sustain_seconds 不发 fire）
    assert transitions == []
    assert states["cascade_fail_high"].first_breach_at == 1060.0


def test_evaluate_breach_sustained_fires() -> None:
    """delta 率持续 >= sustain_seconds 才触发。"""
    states = {
        "cascade_fail_high": _make_state_with_snapshot(
            name="cascade_fail_high",
            last_metrics={"node_total": 1000, "fallback_cascade_fail": 10},
            last_timestamp=1000.0,
            first_breach_at=1000.0,  # 已启动计时
        )
    }
    # 时间过去 700s > 600s 阈值；新增 100 请求 / 30 cascade（30% > 5%）
    ctx = AlertContext(
        timestamp=1700.0,
        requests_total=1100,
        metrics={"node_total": 1100, "fallback_cascade_fail": 40},
    )
    transitions = evaluate(ctx, states)
    assert len(transitions) == 1
    threshold, state, kind = transitions[0]
    assert threshold.name == "cascade_fail_high"
    assert kind == "fire"
    assert state.is_firing


def test_evaluate_recovery_signals() -> None:
    """从 firing → delta 不越线 → 发 recover 信号。"""
    states = {
        "cascade_fail_high": _make_state_with_snapshot(
            name="cascade_fail_high",
            last_metrics={"node_total": 1000, "fallback_cascade_fail": 100},
            last_timestamp=1700.0,
            is_firing=True,
            first_breach_at=1000.0,
            fired_at=1700.0,
        )
    }
    # 新增 100 请求 / 0 cascade（短期 0%）
    ctx = AlertContext(
        timestamp=2000.0,
        requests_total=1100,
        metrics={"node_total": 1100, "fallback_cascade_fail": 100},
    )
    transitions = evaluate(ctx, states)
    assert len(transitions) == 1
    threshold, state, kind = transitions[0]
    assert kind == "recover"
    assert not state.is_firing
    assert state.first_breach_at == 0.0


def test_evaluate_no_double_fire() -> None:
    """已 firing 持续越线不重复发告警。"""
    states = {
        "cascade_fail_high": _make_state_with_snapshot(
            name="cascade_fail_high",
            last_metrics={"node_total": 1000, "fallback_cascade_fail": 10},
            last_timestamp=1700.0,
            is_firing=True,
            first_breach_at=1000.0,
            fired_at=1700.0,
        )
    }
    ctx = AlertContext(
        timestamp=1900.0,
        requests_total=1100,
        metrics={"node_total": 1100, "fallback_cascade_fail": 40},
    )
    transitions = evaluate(ctx, states)
    assert transitions == []


def test_evaluate_app_restart_counter_reset_treated_as_zero_delta() -> None:
    """应用重启后 counter 回 0；delta 视为 0（不能算成负 burst）。"""
    states = {
        "cascade_fail_high": _make_state_with_snapshot(
            name="cascade_fail_high",
            last_metrics={"node_total": 5000, "fallback_cascade_fail": 100},
            last_timestamp=1000.0,
        )
    }
    # 应用重启：counter 从 0 重开
    ctx = AlertContext(
        timestamp=1060.0,
        requests_total=50,
        metrics={"node_total": 50, "fallback_cascade_fail": 2},
    )
    transitions = evaluate(ctx, states)
    # delta 取 max(_, 0) → 不触发告警（即使 2/50 = 4% 也不触发，
    # 因为 node_total delta = 0 算 0/0 → 0%）
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


# ============================================================
# webhook 安全：URL secret 不能泄漏到日志
# ============================================================


def test_webhook_failure_does_not_leak_url_to_log(caplog) -> None:
    """webhook 推送失败时，日志不能含完整 URL（防 secret key 泄漏）。

    企微 webhook URL 形如 `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET`
    httpx 异常 traceback 默认会含完整 URL；自定义 exception handler 必须只
    log 异常类型，不 log exc 全文。
    """
    import logging as _logging
    from unittest.mock import patch as _patch

    from app.observability.alerts import send_wechat_webhook

    fake_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SUPER_SECRET_KEY_DO_NOT_LEAK"

    caplog.set_level(_logging.WARNING, logger="app.observability.alerts")

    # 模拟 httpx.post 抛包含完整 URL 的异常
    class _FakeError(Exception):
        def __str__(self) -> str:
            return f"ConnectError: failed to connect to {fake_url}"

    with _patch("httpx.post", side_effect=_FakeError()):
        result = send_wechat_webhook("test", fake_url)

    assert result is False
    # 全部 warn 日志合并起来不能含 SECRET key 子串
    all_logs = "\n".join(r.getMessage() for r in caplog.records)
    assert "SUPER_SECRET_KEY_DO_NOT_LEAK" not in all_logs, (
        f"webhook URL secret 泄漏到日志：{all_logs}"
    )
