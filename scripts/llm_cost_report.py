#!/usr/bin/env python3
"""LLM 成本报表。

每天跑一次，输出最近 24 小时 token 消耗 + 估算成本：
    0 8 * * * cd /opt/otc-agent && python scripts/llm_cost_report.py >> /var/log/cost.log 2>&1

数据来源（按优先级）：
1. 应用 `/metrics` 本地 counter（最实时，但应用重启会清零）
2. LangFuse trace API 聚合（更准，含 token 详细字段；本期 TODO）

输出格式：
- 按模型拆 token + 估算成本
- 按 direction（prompt / completion）拆
- 按节点拆（如标记）
- 与昨天对比，增长 > 30% 触发告警

环境变量：
    OTC_AGENT_URL                应用 base URL（默认 http://localhost:8000）
    LLM_COST_REPORT_DIR          报表归档目录（默认 /var/lib/otc-agent/cost-reports/）
    LLM_PRICE_PER_M_TOKENS_JSON  单价表 JSON（默认见 _DEFAULT_PRICES）
    WECHAT_ALERT_WEBHOOK_URL     告警群 webhook（成本异常增长时推送）
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import httpx

# 让脚本能直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.observability.metrics import METRIC_LLM_TOKENS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("llm_cost_report")


# ============================================================
# 单价表（每百万 token，单位 USD）
# 按 2026-05 公开定价；现场实际计费以客户合同为准
# ============================================================


_DEFAULT_PRICES = {
    # DeepSeek
    "deepseek-v4-pro": {"prompt": 0.50, "completion": 1.50},
    "deepseek-chat": {"prompt": 0.14, "completion": 0.28},
    # Qwen
    "qwen3-30b-a3b": {"prompt": 0.30, "completion": 0.90},
    "qwen3.5-35b-a3b": {"prompt": 0.30, "completion": 0.90},
    "qwen-max-latest": {"prompt": 2.00, "completion": 6.00},
    "qwen-vl-max-latest": {"prompt": 3.00, "completion": 9.00},
}


def load_prices() -> dict[str, dict[str, float]]:
    """优先从 env JSON 加载，否则用默认价格。"""
    raw = os.environ.get("LLM_PRICE_PER_M_TOKENS_JSON", "")
    if raw:
        try:
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM_PRICE_PER_M_TOKENS_JSON 格式错: %s, 用默认", exc)
    return _DEFAULT_PRICES


# ============================================================
# /metrics 解析（token 部分）
# ============================================================


@dataclass
class TokenBucket:
    """单 (model, direction[, node]) 维度的 token 累计。"""

    model: str
    direction: str  # prompt / completion
    node: str | None
    tokens: float


def fetch_metrics(url: str) -> str:
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:  # noqa: BLE001
        logger.error("fetch_metrics failed: %s", exc)
        return ""


def parse_token_buckets(metrics_text: str) -> list[TokenBucket]:
    """从 /metrics 文本解析 otc_agent_llm_tokens_total 数据。

    匹配格式：
        otc_agent_llm_tokens_total{direction="prompt",model="deepseek-v4-pro"} 12345
        otc_agent_llm_tokens_total{direction="completion",model="deepseek-v4-pro",node="swap.intent"} 234
    """
    out: list[TokenBucket] = []
    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(METRIC_LLM_TOKENS):
            continue
        if "{" not in line:
            continue
        _, rest = line.split("{", 1)
        labels_str, value_str = rest.split("}", 1)
        try:
            value = float(value_str.strip())
        except ValueError:
            continue
        labels = _parse_labels(labels_str)
        out.append(TokenBucket(
            model=labels.get("model", "unknown"),
            direction=labels.get("direction", "prompt"),
            node=labels.get("node"),
            tokens=value,
        ))
    return out


def _parse_labels(labels_str: str) -> dict[str, str]:
    """简化 Prometheus label 解析：k1="v1",k2="v2"。"""
    result: dict[str, str] = {}
    for pair in labels_str.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        result[k.strip()] = v.strip().strip('"')
    return result


# ============================================================
# 成本估算
# ============================================================


def estimate_cost_usd(bucket: TokenBucket, prices: dict[str, dict[str, float]]) -> float:
    """单 bucket 的成本（USD）。"""
    model_prices = prices.get(bucket.model)
    if not model_prices:
        return 0.0
    rate_per_m = model_prices.get(bucket.direction, 0.0)
    return bucket.tokens / 1_000_000 * rate_per_m


def aggregate_by_model(buckets: list[TokenBucket]) -> dict[str, dict[str, float]]:
    """按模型聚合 prompt / completion / total token。"""
    agg: dict[str, dict[str, float]] = defaultdict(lambda: {"prompt": 0.0, "completion": 0.0})
    for b in buckets:
        agg[b.model][b.direction] = agg[b.model].get(b.direction, 0.0) + b.tokens
    for m in agg:
        agg[m]["total"] = agg[m]["prompt"] + agg[m]["completion"]
    return dict(agg)


def aggregate_by_node(buckets: list[TokenBucket]) -> dict[str, float]:
    """按节点聚合（仅含 node label 的 bucket）。"""
    agg: dict[str, float] = defaultdict(float)
    for b in buckets:
        if b.node:
            agg[b.node] += b.tokens
    return dict(agg)


# ============================================================
# 报表归档 + 同比
# ============================================================


def report_dir() -> Path:
    p = Path(os.environ.get("LLM_COST_REPORT_DIR", "/var/lib/otc-agent/cost-reports"))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # 测试或 dev 环境用本地路径
        p = Path("./cost-reports")
        p.mkdir(parents=True, exist_ok=True)
    return p


def save_report(report: dict, when: float | None = None) -> Path:
    when = when if when is not None else time.time()
    fname = time.strftime("cost-%Y%m%d.json", time.localtime(when))
    path = report_dir() / fname
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_yesterday_report(now: float | None = None) -> dict | None:
    now = now if now is not None else time.time()
    yesterday = now - 86400
    fname = time.strftime("cost-%Y%m%d.json", time.localtime(yesterday))
    path = report_dir() / fname
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("load yesterday report failed: %s", exc)
        return None


def compute_growth(today_total: float, yesterday_total: float) -> float:
    """日同比增长率（%）。昨日 0 时返回 0。"""
    if yesterday_total <= 0:
        return 0.0
    return (today_total - yesterday_total) / yesterday_total * 100.0


# ============================================================
# Main
# ============================================================


def build_report(buckets: list[TokenBucket], prices: dict[str, dict[str, float]]) -> dict:
    by_model = aggregate_by_model(buckets)
    by_node = aggregate_by_node(buckets)

    # 成本
    total_cost = 0.0
    cost_by_model: dict[str, float] = {}
    for b in buckets:
        cost = estimate_cost_usd(b, prices)
        total_cost += cost
        cost_by_model[b.model] = cost_by_model.get(b.model, 0.0) + cost

    total_tokens = sum(v["total"] for v in by_model.values())

    return {
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d", time.localtime()),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "by_model": {
            m: {
                "prompt": int(v["prompt"]),
                "completion": int(v["completion"]),
                "total": int(v["total"]),
                "cost_usd": round(cost_by_model.get(m, 0.0), 4),
            }
            for m, v in by_model.items()
        },
        "by_node": {n: int(t) for n, t in by_node.items()},
    }


def maybe_alert_growth(report: dict, growth_pct: float, threshold: float = 30.0) -> None:
    """日同比增长 > threshold → 推告警。"""
    if growth_pct <= threshold:
        return
    msg = (
        f"📈 **LLM 成本异常增长** [P2]\n\n"
        f"日同比：+{growth_pct:.1f}%（阈值 {threshold}%）\n"
        f"今日 tokens：{report['total_tokens']:,}\n"
        f"今日成本：${report['total_cost_usd']}\n"
        f"日期：{report['date']}\n\n"
        f"可能原因：业务量增长 / 调试漏关 trace / cascade fail 循环\n"
        f"参考：docs/operations/observability.md §6\n"
    )
    webhook = os.environ.get("WECHAT_ALERT_WEBHOOK_URL", "")
    if webhook:
        # 延迟导入：alerts 模块可用时；本期不可用则只打印
        try:
            from app.observability.alerts import send_wechat_webhook
            send_wechat_webhook(msg, webhook)
        except ImportError:
            logger.warning("app.observability.alerts 不可用，仅打印")
    logger.warning("成本异常增长告警:\n%s", msg)


def print_report(report: dict, growth_pct: float | None) -> None:
    print(f"\n=== LLM 成本日报 · {report['date']} ===\n")
    print(f"今日 tokens : {report['total_tokens']:,}")
    print(f"今日成本    : ${report['total_cost_usd']}")
    if growth_pct is not None:
        print(f"日同比增长  : {growth_pct:+.1f}%")
    print()
    print("按模型拆：")
    for m, data in report["by_model"].items():
        print(f"  {m:30s} prompt={data['prompt']:>10,}  completion={data['completion']:>10,}  total={data['total']:>10,}  cost=${data['cost_usd']}")
    if report["by_node"]:
        print()
        print("按节点拆：")
        for n, t in sorted(report["by_node"].items(), key=lambda x: -x[1]):
            print(f"  {n:30s} {t:>10,} tokens")


def main() -> int:
    url = os.environ.get("OTC_AGENT_URL", "http://localhost:8000").rstrip("/")
    metrics_text = fetch_metrics(f"{url}/metrics")
    if not metrics_text:
        logger.error("无法拉取 /metrics，退出")
        return 1

    buckets = parse_token_buckets(metrics_text)
    prices = load_prices()
    report = build_report(buckets, prices)

    yesterday = load_yesterday_report()
    growth_pct: float | None = None
    if yesterday:
        growth_pct = compute_growth(report["total_tokens"], yesterday["total_tokens"])

    print_report(report, growth_pct)
    save_path = save_report(report)
    logger.info("报表已归档：%s", save_path)

    if growth_pct is not None:
        maybe_alert_growth(report, growth_pct)

    return 0


if __name__ == "__main__":
    sys.exit(main())
