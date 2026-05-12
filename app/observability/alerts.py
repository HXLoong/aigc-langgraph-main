"""告警评估器（C1.6 / Issue #55）。

基于 C1.5 (#65) `/metrics` endpoint 的实时指标，按 ADR 0017 量化阈值评估
4 类告警，触发时推送到企微告警群（Webhook）。

设计原则：
- **状态机式触发**：只在"未触发 → 触发"或"触发 → 恢复"的状态转换时发消息，
  避免每次评估都重复告警轰炸
- **持续时长约束**：阈值需要"持续 X 分钟"才触发（不被瞬时抖动误报）
- **基于 delta 计算率（self-review #69 修复）**：counters 是累积值，必须取
  与上次评估的差值，才能检测短期突发（不被历史数据稀释）
- **降级**：webhook 推送失败 log.warn，不抛
- 配置全部来自环境变量，便于运维调整

4 类告警（对齐 ADR 0017 + on-call runbook §3）：

| 告警 | 阈值 | 持续 | 严重级 |
|---|---|---|---|
| HTTP 5xx 暴增 | 5xx 率 ≥ 1% | 5 分钟 | P0 |
| Cascade fail 持续 | fallback{reason=cascade_fail} 率 ≥ 5% | 10 分钟 | P1 |
| LLM 失败率高 | llm_total{status!=ok} 率 ≥ 10% | 5 分钟 | P1 |
| HITL 长挂起 | 单 HITL 会话 ≥ 30 分钟 | 即时 | P2（TODO）|
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================
# 阈值配置（对齐 ADR 0017）
# ============================================================


@dataclass(frozen=True)
class AlertThreshold:
    """单条告警的阈值定义。"""

    name: str
    severity: str  # P0 / P1 / P2
    description: str
    threshold_pct: float  # 0-100 百分比，如 5.0 表示 5%
    sustain_seconds: int  # 持续多少秒才触发


THRESHOLDS: dict[str, AlertThreshold] = {
    "http_5xx_spike": AlertThreshold(
        name="http_5xx_spike",
        severity="P0",
        description="HTTP 5xx 率 ≥ 1% 持续 5 分钟",
        threshold_pct=1.0,
        sustain_seconds=300,
    ),
    "cascade_fail_high": AlertThreshold(
        name="cascade_fail_high",
        severity="P1",
        description="Cascade fail 率 ≥ 5% 持续 10 分钟",
        threshold_pct=5.0,
        sustain_seconds=600,
    ),
    "llm_failure_high": AlertThreshold(
        name="llm_failure_high",
        severity="P1",
        description="LLM 调用失败率 ≥ 10% 持续 5 分钟",
        threshold_pct=10.0,
        sustain_seconds=300,
    ),
}


# ============================================================
# 状态：哪些告警在 firing
# ============================================================


@dataclass
class AlertState:
    """单条告警的运行时状态。

    last_metrics + last_timestamp 用于 delta 计算（self-review #69 修复）：
    counter 是累积值，必须与上次评估求差才能反映"最近窗口"的率，否则历史
    数据会稀释短期突发（如长时间运行后突发 30 cascade fail 被历史数据淹没）。
    """

    name: str
    is_firing: bool = False
    first_breach_at: float = 0.0  # epoch seconds；首次越线时间
    fired_at: float = 0.0  # 已发告警的时间（防短期重发）
    # 上次评估的 metrics 累积值快照（仅用于 delta 计算）
    last_metrics: dict[str, float] = field(default_factory=dict)
    last_timestamp: float = 0.0  # 上次评估时刻；首次评估时为 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "is_firing": self.is_firing,
            "first_breach_at": self.first_breach_at,
            "fired_at": self.fired_at,
            "last_metrics": self.last_metrics,
            "last_timestamp": self.last_timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlertState":
        return cls(
            name=data["name"],
            is_firing=data.get("is_firing", False),
            first_breach_at=data.get("first_breach_at", 0.0),
            fired_at=data.get("fired_at", 0.0),
            last_metrics=dict(data.get("last_metrics", {})),
            last_timestamp=data.get("last_timestamp", 0.0),
        )


@dataclass
class AlertContext:
    """评估时的输入快照。"""

    timestamp: float  # 当前 epoch seconds
    requests_total: int  # 总请求数（用于计算分子分母）
    metrics: dict[str, Any] = field(default_factory=dict)  # 从 /metrics parse 的数据


# ============================================================
# 持久化状态（跨 cron 调用记忆"已触发"）
# ============================================================


def _state_file_path() -> Path:
    """状态文件位置，可通过 ALERT_STATE_FILE 覆盖。"""
    return Path(
        os.environ.get(
            "ALERT_STATE_FILE",
            "/tmp/otc_agent_alert_state.json",
        )
    )


def load_state() -> dict[str, AlertState]:
    """加载所有告警的状态。文件不存在 / 格式坏 → 空 dict。"""
    p = _state_file_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: AlertState.from_dict(v) for k, v in data.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("alerts: state load failed (%s), starting fresh", exc)
        return {}


def save_state(states: dict[str, AlertState]) -> None:
    p = _state_file_path()
    try:
        p.write_text(
            json.dumps({k: v.to_dict() for k, v in states.items()}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("alerts: state save failed: %s", exc)


# ============================================================
# 阈值评估
# ============================================================


def _calc_ratio_pct(numerator: float, denominator: float) -> float:
    """计算分子/分母百分比；分母 0 时返回 0。"""
    if denominator <= 0:
        return 0.0
    return (numerator / denominator) * 100.0


def evaluate(
    ctx: AlertContext,
    states: dict[str, AlertState] | None = None,
) -> list[tuple[AlertThreshold, AlertState, str]]:
    """评估全部告警，返回需要发送的告警列表。

    采用 **delta-based rate**：用当前 counter - 上次 counter 算"最近窗口"的率，
    避免累积值被历史数据稀释。

    **首次评估**（state.last_timestamp == 0）只记 snapshot，不评估告警——
    避免冷启动时立刻拿累积值算率误报。

    Returns:
        list of (threshold, state, transition) tuples
        transition: "fire"（新触发）或 "recover"（已恢复）
    """
    if states is None:
        states = {}
    out: list[tuple[AlertThreshold, AlertState, str]] = []
    now = ctx.timestamp

    for name, threshold in THRESHOLDS.items():
        state = states.setdefault(name, AlertState(name=name))

        # 首次评估（or 状态文件被清空）：只记 snapshot 不评估
        if state.last_timestamp == 0.0:
            state.last_metrics = dict(ctx.metrics)
            state.last_timestamp = now
            continue

        current_pct = _delta_ratio_pct(name, ctx, state)
        breach = current_pct >= threshold.threshold_pct

        if breach:
            if state.first_breach_at == 0.0:
                state.first_breach_at = now
            sustain = now - state.first_breach_at
            if sustain >= threshold.sustain_seconds and not state.is_firing:
                state.is_firing = True
                state.fired_at = now
                out.append((threshold, state, "fire"))
        else:
            # 未越线：清零累计 + 如果在 firing 状态发"恢复"
            if state.is_firing:
                state.is_firing = False
                out.append((threshold, state, "recover"))
            state.first_breach_at = 0.0

        # 更新 snapshot 供下次评估
        state.last_metrics = dict(ctx.metrics)
        state.last_timestamp = now

    return out


def _delta_ratio_pct(name: str, ctx: AlertContext, state: AlertState) -> float:
    """计算当前告警在"上次评估 → 本次评估"窗口内的率（百分比）。

    用 delta 而非累积值——避免历史数据稀释短期突发。
    """
    current = ctx.metrics
    previous = state.last_metrics

    def delta(key: str) -> float:
        """counter 单调递增；理论上 current >= previous，应用重启会 reset
        让 previous > current。重启场景 delta 视为 0（避免负数当 burst）。"""
        d = current.get(key, 0) - previous.get(key, 0)
        return max(d, 0.0)

    if name == "http_5xx_spike":
        # TODO: 接 nginx exporter 或 FastAPI HTTP 中间件计数（C1.6 后续 PR）
        return _calc_ratio_pct(delta("http_5xx"), delta("node_total"))

    if name == "cascade_fail_high":
        return _calc_ratio_pct(delta("fallback_cascade_fail"), delta("node_total"))

    if name == "llm_failure_high":
        return _calc_ratio_pct(delta("llm_error"), delta("llm_total"))

    return 0.0


# ============================================================
# /metrics 解析
# ============================================================


def parse_prometheus_metrics(text: str) -> dict[str, Any]:
    """解析 /metrics endpoint 输出，提取本任务需要的数值。

    简化解析：不引入 prometheus_client 客户端依赖，按字符串前缀匹配。
    """
    result: dict[str, Any] = {
        "http_5xx": 0,
        "fallback_cascade_fail": 0,
        "llm_error": 0,
        "llm_total": 0,
        "node_total": 0,
    }
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 解析 metric_name{labels} value
        if "{" in line:
            name_part, rest = line.split("{", 1)
            labels_str, value_str = rest.split("}", 1)
            value = float(value_str.strip())
            if name_part == "otc_agent_fallback_total" and 'reason="cascade_fail"' in labels_str:
                result["fallback_cascade_fail"] += value
            elif name_part == "otc_agent_llm_total":
                result["llm_total"] += value
                if 'status="error"' in labels_str or 'status="timeout"' in labels_str:
                    result["llm_error"] += value
            elif name_part == "otc_agent_node_total":
                result["node_total"] += value
        # http_5xx 通过外部 nginx 日志接入；本期 stub 为 0
    return result


# ============================================================
# 推送到企微 webhook
# ============================================================


def format_alert_message(threshold: AlertThreshold, transition: str, ctx: AlertContext) -> str:
    """格式化企微消息文本。"""
    icon = "🔥" if transition == "fire" else "✅"
    state_text = "触发" if transition == "fire" else "恢复"
    return (
        f"{icon} **otc-agent 告警 {state_text}** [{threshold.severity}]\n\n"
        f"告警名：`{threshold.name}`\n"
        f"描述：{threshold.description}\n"
        f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ctx.timestamp))}\n"
        f"参考：on-call runbook §3 / troubleshooting-sop\n"
    )


def send_wechat_webhook(message: str, webhook_url: str) -> bool:
    """发企微 webhook。失败返回 False 不抛。

    **安全**：异常处理只 log exception 类型，不 log exc 全文——企微 webhook
    URL 含 secret key（`?key=SECRET`），httpx exc 默认会把完整请求 URL
    放入 message/traceback，写入日志可能被监控/审计系统采集泄漏。
    """
    try:
        import httpx

        payload = {"msgtype": "markdown", "markdown": {"content": message}}
        resp = httpx.post(webhook_url, json=payload, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("errcode") == 0:
                return True
            # 业务错误码不含 URL，可安全 log
            logger.warning(
                "alerts: webhook errcode=%s msg=%s",
                data.get("errcode"), data.get("errmsg"),
            )
        else:
            logger.warning("alerts: webhook HTTP %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001
        # 只 log 异常类型，不 log exc 全文（防 URL secret 泄漏到日志）
        logger.warning("alerts: webhook send failed: %s", type(exc).__name__)
    return False


__all__ = [
    "AlertThreshold",
    "AlertState",
    "AlertContext",
    "THRESHOLDS",
    "load_state",
    "save_state",
    "evaluate",
    "parse_prometheus_metrics",
    "format_alert_message",
    "send_wechat_webhook",
]
