"""告警评估器（C1.6 / Issue #55）。

基于 C1.5 (#65) `/metrics` endpoint 的实时指标，按 ADR 0017 量化阈值评估
4 类告警，触发时推送到企微告警群（Webhook）。

设计原则：
- **状态机式触发**：只在"未触发 → 触发"或"触发 → 恢复"的状态转换时发消息，
  避免每次评估都重复告警轰炸
- **持续时长约束**：阈值需要"持续 X 分钟"才触发（不被瞬时抖动误报）
- **HITL 长挂起特殊处理**：基于 LangFuse trace 查询（本期不实现，留 TODO）
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
    """单条告警的运行时状态。"""

    name: str
    is_firing: bool = False
    first_breach_at: float = 0.0  # epoch seconds；首次越线时间
    fired_at: float = 0.0  # 已发告警的时间（防短期重发）

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "is_firing": self.is_firing,
            "first_breach_at": self.first_breach_at,
            "fired_at": self.fired_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AlertState":
        return cls(
            name=data["name"],
            is_firing=data.get("is_firing", False),
            first_breach_at=data.get("first_breach_at", 0.0),
            fired_at=data.get("fired_at", 0.0),
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
        current_pct = _current_ratio_pct(name, ctx)
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

    return out


def _current_ratio_pct(name: str, ctx: AlertContext) -> float:
    """从 metrics 计算当前告警的"率"百分比。"""
    metrics = ctx.metrics
    total = ctx.requests_total

    if name == "http_5xx_spike":
        # 来自反向代理日志或 fastapi 中间件；本期暂用 cascade_fail 作为代理信号
        # 真实部署应接 nginx access log 5xx 计数
        # TODO: 接 nginx exporter 或自实现 HTTP 状态中间件
        return _calc_ratio_pct(metrics.get("http_5xx", 0), total)

    if name == "cascade_fail_high":
        cascade = metrics.get("fallback_cascade_fail", 0)
        return _calc_ratio_pct(cascade, total)

    if name == "llm_failure_high":
        llm_error = metrics.get("llm_error", 0)
        llm_total = metrics.get("llm_total", 0)
        return _calc_ratio_pct(llm_error, llm_total)

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
    """发企微 webhook。失败返回 False 不抛。"""
    try:
        import httpx

        payload = {"msgtype": "markdown", "markdown": {"content": message}}
        resp = httpx.post(webhook_url, json=payload, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("errcode") == 0:
                return True
            logger.warning("alerts: webhook errcode=%s msg=%s", data.get("errcode"), data.get("errmsg"))
        else:
            logger.warning("alerts: webhook HTTP %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alerts: webhook send failed: %s", exc)
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
