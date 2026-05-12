#!/usr/bin/env python3
"""告警 cron 入口（C1.6 / Issue #55）。

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
    """拉应用 /metrics endpoint。"""
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001
        logger.error("fetch_metrics failed: %s", exc)
        return ""


def main() -> int:
    app_url = os.environ.get("OTC_AGENT_URL", "http://localhost:8000").rstrip("/")
    webhook_url = os.environ.get("WECHAT_ALERT_WEBHOOK_URL", "")

    metrics_text = fetch_metrics(f"{app_url}/metrics")
    if not metrics_text:
        logger.warning("metrics empty, skipping alert evaluation")
        return 0

    metrics = parse_prometheus_metrics(metrics_text)
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
