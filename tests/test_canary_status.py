"""scripts/canary_status.py · 解析器 + 模式判定测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.canary_status import (
    CanaryStatus,
    _describe_mode,
    _parse_canary_counters,
)


# ============================================================
# _parse_canary_counters
# ============================================================


def test_parse_both_labels_present() -> None:
    text = """
# TYPE otc_agent_canary_traffic_total counter
otc_agent_canary_traffic_total{is_canary="true"} 142
otc_agent_canary_traffic_total{is_canary="false"} 3
"""
    assert _parse_canary_counters(text) == (142, 3)


def test_parse_only_canary_true() -> None:
    text = 'otc_agent_canary_traffic_total{is_canary="true"} 100\n'
    assert _parse_canary_counters(text) == (100, 0)


def test_parse_empty_metrics() -> None:
    """无 canary 计数 → 0/0。"""
    assert _parse_canary_counters("") == (0, 0)


def test_parse_ignores_comments_and_unrelated() -> None:
    text = """
# HELP otc_agent_canary_traffic_total ...
# TYPE otc_agent_canary_traffic_total counter
otc_agent_node_total{node="ingest",status="ok"} 999
otc_agent_canary_traffic_total{is_canary="true"} 50
"""
    assert _parse_canary_counters(text) == (50, 0)


def test_parse_handles_malformed_lines() -> None:
    """损坏的 metric 行不能让整个解析崩。"""
    text = """
otc_agent_canary_traffic_total{is_canary="true"} 42
otc_agent_canary_traffic_total{broken_line_without_close
otc_agent_canary_traffic_total{is_canary="false"} 7
"""
    canary, non_canary = _parse_canary_counters(text)
    assert canary == 42
    assert non_canary == 7


def test_parse_handles_float_values() -> None:
    """Prometheus exposition 允许 float 值，应当 truncate 到 int。"""
    text = 'otc_agent_canary_traffic_total{is_canary="true"} 3.0\n'
    assert _parse_canary_counters(text) == (3, 0)


# ============================================================
# _describe_mode
# ============================================================


def test_mode_empty_allowlist() -> None:
    assert "未启用" in _describe_mode([])


def test_mode_all_marker() -> None:
    assert "全量" in _describe_mode(["ALL"])


def test_mode_f42_first_phase() -> None:
    """1-2 个群 → F4.2 描述。"""
    assert "F4.2" in _describe_mode(["r-test-1"])
    assert "F4.2" in _describe_mode(["r-test-1", "r-test-2"])


def test_mode_f43_multi_room() -> None:
    """> 2 个群 → F4.3+ 描述。"""
    assert "F4.3" in _describe_mode([f"r-{i}" for i in range(10)])


# ============================================================
# CanaryStatus · is_breach 判定
# ============================================================


def _status(allowlist: list[str], canary: int, non_canary: int) -> CanaryStatus:
    return CanaryStatus(
        timestamp="2026-05-12 11:30:00",
        metrics_url_host="localhost",
        allowlist=allowlist,
        mode=_describe_mode(allowlist),
        canary_count=canary,
        non_canary_count=non_canary,
    )


def test_breach_when_non_canary_present_and_not_all() -> None:
    s = _status(["r-test-1"], canary=100, non_canary=3)
    assert s.is_breach is True


def test_no_breach_when_non_canary_zero() -> None:
    s = _status(["r-test-1"], canary=100, non_canary=0)
    assert s.is_breach is False


def test_no_breach_when_all_marker_even_if_non_canary_present() -> None:
    """ALL 全量模式：任何 roomId 都视为 canary，is_canary=false 的指标本不应有，
    但即便有也不算 breach（数据滞后）。"""
    s = _status(["ALL"], canary=500, non_canary=2)
    assert s.is_breach is False


def test_total_property() -> None:
    assert _status(["r-1"], canary=10, non_canary=5).total == 15


def test_no_breach_when_allowlist_empty() -> None:
    """allowlist 空 = 金丝雀未启用，non_canary > 0 也算 breach（保守判定）。"""
    # 注意：未启用时所有进入流量都是 non_canary，is_breach 仍是 True，
    # 提醒运维"金丝雀模式未启用但有流量进入" —— 这是有意行为
    s = _status([], canary=0, non_canary=10)
    assert s.is_breach is True
