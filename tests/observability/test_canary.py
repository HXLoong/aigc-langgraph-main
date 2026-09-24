"""金丝雀切流监控测试。"""
from __future__ import annotations

import pytest

from app.observability import canary as canary_mod
from app.observability import metrics


@pytest.fixture
def restore_canary_state(monkeypatch: pytest.MonkeyPatch):
    """每个测试独立 reload allowlist；测试结束自动恢复。"""
    original = canary_mod._CANARY_ROOM_IDS
    yield monkeypatch
    canary_mod._CANARY_ROOM_IDS = original


@pytest.fixture(autouse=True)
def reset_metrics_collector():
    metrics.get_collector().reset()
    yield
    metrics.get_collector().reset()


# ============================================================
# is_canary_room · 白名单语义
# ============================================================


def test_canary_room_in_allowlist(restore_canary_state, monkeypatch) -> None:
    monkeypatch.setenv("CANARY_ROOM_IDS", "r-test-1,r-test-2")
    canary_mod.reload_canary_room_ids()
    assert canary_mod.is_canary_room("r-test-1") is True
    assert canary_mod.is_canary_room("r-test-2") is True


def test_non_canary_room_not_in_allowlist(restore_canary_state, monkeypatch) -> None:
    monkeypatch.setenv("CANARY_ROOM_IDS", "r-test-1")
    canary_mod.reload_canary_room_ids()
    assert canary_mod.is_canary_room("r-prod-anything") is False


def test_empty_allowlist_returns_false(restore_canary_state, monkeypatch) -> None:
    """allowlist 未设置 → 任何 roomId 都不算 canary（金丝雀未启用）。"""
    monkeypatch.delenv("CANARY_ROOM_IDS", raising=False)
    canary_mod.reload_canary_room_ids()
    assert canary_mod.is_canary_room("r-anything") is False


def test_all_marker_means_full_rollout(restore_canary_state, monkeypatch) -> None:
    """ALL 特殊值表示全量上线。"""
    monkeypatch.setenv("CANARY_ROOM_IDS", "ALL")
    canary_mod.reload_canary_room_ids()
    assert canary_mod.is_canary_room("r-any-room") is True
    assert canary_mod.is_canary_room("r-prod-9999") is True


def test_none_or_empty_room_id_not_canary() -> None:
    assert canary_mod.is_canary_room(None) is False
    assert canary_mod.is_canary_room("") is False


def test_room_id_with_spaces_trimmed(restore_canary_state, monkeypatch) -> None:
    """逗号分隔的 token 头尾空格被 strip。"""
    monkeypatch.setenv("CANARY_ROOM_IDS", "  r-1  ,  r-2  ")
    canary_mod.reload_canary_room_ids()
    assert canary_mod.is_canary_room("r-1") is True
    assert canary_mod.is_canary_room("r-2") is True


def test_get_canary_room_ids_returns_frozenset(restore_canary_state, monkeypatch) -> None:
    monkeypatch.setenv("CANARY_ROOM_IDS", "r-1,r-2")
    canary_mod.reload_canary_room_ids()
    ids = canary_mod.get_canary_room_ids()
    assert isinstance(ids, frozenset)
    assert ids == frozenset({"r-1", "r-2"})


# ============================================================
# emit_canary_traffic · metric 埋点
# ============================================================


def test_emit_canary_metric_for_canary_room() -> None:
    metrics.emit_canary_traffic(is_canary=True)
    coll = metrics.get_collector()
    assert (
        coll.get_counter(metrics.METRIC_CANARY_TRAFFIC_TOTAL, {"is_canary": "true"}) == 1
    )
    assert (
        coll.get_counter(metrics.METRIC_CANARY_TRAFFIC_TOTAL, {"is_canary": "false"}) == 0
    )


def test_emit_canary_metric_for_non_canary_room() -> None:
    metrics.emit_canary_traffic(is_canary=False)
    coll = metrics.get_collector()
    assert (
        coll.get_counter(metrics.METRIC_CANARY_TRAFFIC_TOTAL, {"is_canary": "false"}) == 1
    )


# ============================================================
# ingest 节点集成
# ============================================================


@pytest.mark.asyncio
async def test_ingest_emits_canary_metric_canary_room(
    restore_canary_state, monkeypatch
) -> None:
    from app.nodes.ingest import ingest

    monkeypatch.setenv("CANARY_ROOM_IDS", "r-canary-1")
    canary_mod.reload_canary_room_ids()
    await ingest({"room_id": "r-canary-1"})  # type: ignore[arg-type]

    coll = metrics.get_collector()
    assert coll.get_counter(metrics.METRIC_CANARY_TRAFFIC_TOTAL, {"is_canary": "true"}) == 1
    assert coll.get_counter(metrics.METRIC_CANARY_TRAFFIC_TOTAL, {"is_canary": "false"}) == 0


@pytest.mark.asyncio
async def test_ingest_emits_metric_for_non_canary_room(
    restore_canary_state, monkeypatch
) -> None:
    """切流期间误切非测试群的 agentUrl → ingest 应记 is_canary=false。"""
    from app.nodes.ingest import ingest

    monkeypatch.setenv("CANARY_ROOM_IDS", "r-canary-1")
    canary_mod.reload_canary_room_ids()
    await ingest({"room_id": "r-leaked-prod-room"})  # type: ignore[arg-type]

    coll = metrics.get_collector()
    assert coll.get_counter(metrics.METRIC_CANARY_TRAFFIC_TOTAL, {"is_canary": "false"}) == 1


# ============================================================
# alerts non_canary_traffic 阈值
# ============================================================


def test_alerts_non_canary_threshold_present() -> None:
    """新告警阈值 non_canary_traffic 已注册。"""
    from app.observability.alerts import THRESHOLDS

    assert "non_canary_traffic" in THRESHOLDS
    threshold = THRESHOLDS["non_canary_traffic"]
    assert threshold.severity == "P0"
    assert threshold.sustain_seconds == 0  # 即时触发


def test_alerts_parse_canary_traffic_non_canary() -> None:
    """parse_prometheus_metrics 提取 canary_traffic_non_canary 累积值。"""
    from app.observability.alerts import parse_prometheus_metrics

    text = """
# TYPE otc_agent_canary_traffic_total counter
otc_agent_canary_traffic_total{is_canary="true"} 100
otc_agent_canary_traffic_total{is_canary="false"} 3
"""
    parsed = parse_prometheus_metrics(text)
    assert parsed["canary_traffic_non_canary"] == 3.0


def test_alerts_evaluate_non_canary_fires_on_any_traffic() -> None:
    """≥ 1 条 non-canary 流量即触发（sustain_seconds=0 即时）。"""
    from app.observability.alerts import AlertContext, evaluate

    # 第一次评估只记 snapshot
    ctx1 = AlertContext(
        timestamp=1000.0,
        requests_total=10,
        metrics={"canary_traffic_non_canary": 0, "node_total": 10},
    )
    states: dict = {}
    evaluate(ctx1, states)

    # 第二次评估 delta = 1 → 越线
    ctx2 = AlertContext(
        timestamp=1010.0,
        requests_total=11,
        metrics={"canary_traffic_non_canary": 1, "node_total": 11},
    )
    out = evaluate(ctx2, states)
    fired = [t for t, _, transition in out if transition == "fire"]
    assert any(t.name == "non_canary_traffic" for t in fired)
