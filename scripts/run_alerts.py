#!/usr/bin/env python3
"""告警 cron 入口。

每分钟跑一次（cron 配置）：
    * * * * * cd /opt/otc-agent && python scripts/run_alerts.py >> /var/log/alerts.log 2>&1

工作流：
1. 拉应用 /metrics endpoint
2. 解析 Prometheus 文本
3. 加载持久化状态（哪些告警还在 firing）
4. 评估 4 类告警阈值
5. 状态转换时（fire / recover）推企微 webhook
6. 保存新状态

环境变量：
    OTC_AGENT_URL              应用 base URL，默认 http://localhost:8000
    WECHAT_ALERT_WEBHOOK_URL   企微告警群 webhook URL（不配则只打印不推送）
    ALERT_STATE_FILE           状态持久化路径，默认 /tmp/otc_agent_alert_state.json
"""
from __future__ import annotations

import logging
import os
import sys
import time

import httpx

# 让脚本能直接运行（不通过 -m）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.observability.alerts import (
    AlertContext,
    evaluate,
    format_alert_message,
    load_state,
    parse_prometheus_metrics,
    save_state,
    send_wechat_webhook,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("run_alerts")


def fetch_metrics(url: str) -> str:
    """拉应用 /metrics endpoint。失败返回空串（不抛）。"""
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001
        # 只 log 异常类型 + URL host，避免 traceback 泄漏完整 URL（与 webhook 同理）
        logger.error("fetch_metrics failed: %s", type(exc).__name__)
        return ""


def _send_watchdog_alert(webhook_url: str) -> None:
    """metrics 拉取失败时发 watchdog 告警（监控失联本身也是告警事件）。

    避免一直静默——/metrics 不通可能意味着应用 down 或网络问题。
    """
    msg = (
        "🚨 **otc-agent 监控失联** [P1]\n\n"
        "无法拉取应用 /metrics endpoint。\n"
        f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "可能原因：应用 down / 网络不通 / 健康检查未启用。\n"
        "处置：见 on-call runbook §5.1（5xx 崩溃）。\n"
    )
    logger.warning("watchdog: metrics 失联")
    if webhook_url:
        send_wechat_webhook(msg, webhook_url)


def main() -> int:
    app_url = os.environ.get("OTC_AGENT_URL", "http://localhost:8000").rstrip("/")
    webhook_url = os.environ.get("WECHAT_ALERT_WEBHOOK_URL", "")

    metrics_text = fetch_metrics(f"{app_url}/metrics")
    if not metrics_text:
        # self-review 必修项：metrics 拉空时**不**调 evaluate
        # 避免全 0 metrics 被误判为"业务恢复"触发虚假 recover 信号；
        # 改为发 watchdog 告警（监控失联也是告警事件）。
        logger.warning("metrics empty, skipping evaluation; sending watchdog alert")
        _send_watchdog_alert(webhook_url)
        return 0

    metrics = parse_prometheus_metrics(metrics_text)

    # node_total == 0 意味着应用刚启动还无请求（合法场景）。
    # delta 计算下首次评估只记 snapshot，第二次评估时 delta=0 不会误触发。
    ctx = AlertContext(
        timestamp=time.time(),
        requests_total=int(metrics.get("node_total", 0)),
        metrics=metrics,
    )

    states = load_state()
    transitions = evaluate(ctx, states)

    for threshold, state, transition in transitions:
        msg = format_alert_message(threshold, transition, ctx)
        logger.info("alert %s: %s", transition, threshold.name)
        if webhook_url:
            send_wechat_webhook(msg, webhook_url)
        else:
            logger.info("WECHAT_ALERT_WEBHOOK_URL 未配置，仅打印不推送:\n%s", msg)

    save_state(states)
    return 0


if __name__ == "__main__":
    sys.exit(main())
