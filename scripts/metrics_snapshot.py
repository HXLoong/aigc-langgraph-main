#!/usr/bin/env python3
"""LangGraph 全指标快照（告警 / 成本 / 金丝雀 / 健康检查可视化）。

金丝雀切流期间 Tony / 业务方 / on-call 查"当前 LangGraph 健康状态"
的运维 CLI。不需要 Grafana / Prometheus 客户端，纯 HTTP + 文本解析。

跑法：
    python scripts/metrics_snapshot.py                                # 本地默认
    python scripts/metrics_snapshot.py --url http://prod:8000/metrics
    python scripts/metrics_snapshot.py --json                         # 机器可读

输出（人读）：
    === LangGraph 指标快照 · {timestamp} · host={host} ===

    ## 节点级（otc_agent_node_total）
    | 节点 | ok | error | 错误率 |
    |---|---|---|---|
    | ingest          | 142 |  0 | 0.0%
    | intent_route    | 142 |  0 | 0.0%
    ...

    ## 业务指标
    Fallback 触发: 12（reason=cascade_fail:9 / backend_unreachable:3）
    LLM 调用: 287（ok:280 error:7 = 2.4% 失败率）
    LLM token 消耗: prompt=1.2M completion=345K

    ## 金丝雀（otc_agent_canary_traffic_total）
    is_canary=true:  142
    is_canary=false: 0  ✅

    ## 健康检查（otc_agent_health_check_total）
    mysql=ok:60        langfuse=disabled:60
    llm=ok:60          java_backend=ok:60

退出码：
    0 OK
    2 metrics endpoint 不可达
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from time import strftime
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass
class MetricsSnapshot:
    timestamp: str
    host: str
    # name → labels_tuple → value
    counters: dict[str, dict[tuple, float]] = field(default_factory=dict)


def _fetch_metrics(url: str, timeout: float = 5.0) -> str:
    try:
        r = httpx.get(url, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: 无法访问 {url}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def _parse_labels(labels_str: str) -> tuple:
    """`is_canary="true",target="mysql"` → (('is_canary','true'), ('target','mysql'))"""
    out: list[tuple[str, str]] = []
    for part in labels_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out.append((k.strip(), v.strip().strip('"')))
    return tuple(sorted(out))


def _parse_metrics(text: str) -> dict[str, dict[tuple, float]]:
    """保留 counter 和经典 histogram 样本，供文本及 JSON 快照使用。"""
    counters: dict[str, dict[tuple, float]] = defaultdict(dict)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "{" not in line:
            # 无 label 的 counter
            try:
                name, value_str = line.rsplit(" ", 1)
            except ValueError:
                continue
            try:
                counters[name][()] = float(value_str)
            except ValueError:
                continue
            continue
        try:
            name, rest = line.split("{", 1)
            labels_str, value_str = rest.split("}", 1)
        except ValueError:
            continue
        try:
            value = float(value_str.strip())
        except ValueError:
            continue
        labels = _parse_labels(labels_str)
        counters[name][labels] = value
    return counters


def _sum_by_label(
    counter: dict[tuple, float], label_key: str
) -> dict[str, float]:
    """把 counter 按指定 label 维度求和。"""
    out: dict[str, float] = defaultdict(float)
    for labels, value in counter.items():
        for k, v in labels:
            if k == label_key:
                out[v] += value
                break
    return dict(out)


# ============================================================
# 渲染各段
# ============================================================


def _render_node_section(counters: dict[str, dict[tuple, float]]) -> list[str]:
    lines: list[str] = ["## 节点级 (otc_agent_node_total)"]
    node_counter = counters.get("otc_agent_node_total", {})
    if not node_counter:
        lines.append("  （无数据）")
        return lines

    # 按 node 聚合 ok / error
    by_node: dict[str, dict[str, float]] = defaultdict(lambda: {"ok": 0.0, "error": 0.0})
    for labels, value in node_counter.items():
        label_dict = dict(labels)
        node = label_dict.get("node", "unknown")
        status = label_dict.get("status", "unknown")
        by_node[node][status] = by_node[node].get(status, 0) + value

    lines.append(f"  {'节点':<22}{'ok':>8}{'error':>8}  错误率")
    for node in sorted(by_node):
        ok = by_node[node].get("ok", 0)
        err = by_node[node].get("error", 0)
        total = ok + err
        rate = (err / total * 100) if total else 0.0
        marker = "  ⚠️" if rate >= 5 else ""
        lines.append(f"  {node:<22}{int(ok):>8}{int(err):>8}  {rate:.1f}%{marker}")
    return lines


def _render_business_section(counters: dict[str, dict[tuple, float]]) -> list[str]:
    lines: list[str] = ["## 业务指标"]

    fallback = counters.get("otc_agent_fallback_total", {})
    fallback_total = int(sum(fallback.values()))
    fallback_by_reason = {
        k: int(v) for k, v in _sum_by_label(fallback, "reason").items()
    }
    if fallback_total:
        breakdown = " ".join(f"{k}:{v}" for k, v in sorted(fallback_by_reason.items()))
        lines.append(f"  Fallback 触发: {fallback_total} ({breakdown})")
    else:
        lines.append("  Fallback 触发: 0")

    llm = counters.get("otc_agent_llm_total", {})
    llm_total = int(sum(llm.values()))
    llm_by_status = {k: int(v) for k, v in _sum_by_label(llm, "status").items()}
    err_count = llm_by_status.get("error", 0) + llm_by_status.get("timeout", 0)
    err_rate = (err_count / llm_total * 100) if llm_total else 0.0
    marker = "  ⚠️" if err_rate >= 10 else ""
    lines.append(
        f"  LLM 调用: {llm_total} (ok:{llm_by_status.get('ok', 0)} "
        f"error:{llm_by_status.get('error', 0)} timeout:{llm_by_status.get('timeout', 0)} "
        f"= {err_rate:.1f}% 失败率){marker}"
    )

    tokens = counters.get("otc_agent_llm_tokens_total", {})
    by_direction = _sum_by_label(tokens, "direction")
    if by_direction:
        prompt = int(by_direction.get("prompt", 0))
        completion = int(by_direction.get("completion", 0))
        lines.append(
            f"  LLM token 消耗: prompt={prompt:,} completion={completion:,}"
        )

    return lines


def _render_canary_section(counters: dict[str, dict[tuple, float]]) -> list[str]:
    lines: list[str] = ["## 金丝雀 (otc_agent_canary_traffic_total)"]
    canary = counters.get("otc_agent_canary_traffic_total", {})
    if not canary:
        lines.append("  （无数据，金丝雀未启用或服务未收到请求）")
        return lines
    by_is_canary = {k: int(v) for k, v in _sum_by_label(canary, "is_canary").items()}
    canary_n = by_is_canary.get("true", 0)
    non_canary_n = by_is_canary.get("false", 0)
    marker = "  ❌ 误切告警！" if non_canary_n > 0 else "  ✅"
    lines.append(f"  is_canary=true:  {canary_n}")
    lines.append(f"  is_canary=false: {non_canary_n}{marker}")
    return lines


def _render_health_section(counters: dict[str, dict[tuple, float]]) -> list[str]:
    lines: list[str] = ["## 健康检查 (otc_agent_health_check_total)"]
    health = counters.get("otc_agent_health_check_total", {})
    if not health:
        lines.append("  （无数据，/ready 尚未被调用）")
        return lines
    # 按 target 聚合 ok / fail / disabled
    by_target: dict[str, dict[str, int]] = defaultdict(
        lambda: {"ok": 0, "fail": 0, "disabled": 0}
    )
    for labels, value in health.items():
        d = dict(labels)
        target = d.get("target", "unknown")
        status = d.get("status", "unknown")
        by_target[target][status] = by_target[target].get(status, 0) + int(value)
    for target in sorted(by_target):
        st = by_target[target]
        mark = "❌" if st.get("fail", 0) > 0 else "✅"
        lines.append(
            f"  {target:<16} ok={st.get('ok', 0)} fail={st.get('fail', 0)} "
            f"disabled={st.get('disabled', 0)}  {mark}"
        )
    return lines


def _render_http_section(counters: dict[str, dict[tuple, float]]) -> list[str]:
    lines = ["## HTTP 请求累计（单次快照，不代表滚动窗口通过率）"]
    requests = counters.get("otc_agent_http_total", {})
    total = sum(requests.values())
    if total <= 0:
        return [*lines, "  （无 HTTP 请求样本，错误率不可计算）"]
    errors = sum(value for labels, value in requests.items()
                 if dict(labels).get("status_class") == "5xx")
    cascade = sum(value for labels, value in counters.get("otc_agent_fallback_total", {}).items()
                  if dict(labels).get("reason") == "cascade_fail")
    lines.extend([
        f"  HTTP 请求累计: {total:g}",
        f"  5xx: {errors:g} ({errors / total:.2%})",
        f"  cascade_fail: {cascade:g} ({cascade / total:.2%})",
    ])
    return lines


def _render_histogram_section(counters: dict[str, dict[tuple, float]]) -> list[str]:
    lines = ["## Histogram 原始累计样本（_sum / _count / _bucket）"]
    for name, samples in sorted(counters.items()):
        if not name.endswith(("_bucket", "_sum", "_count")):
            continue
        for labels, value in sorted(samples.items()):
            scope = dict(labels).get("node") or (
                "端到端" if name.startswith("otc_agent_intent_latency_ms_") else "无节点标签"
            )
            label_text = ",".join(f'{key}="{val}"' for key, val in labels)
            lines.append(f"  {name}{{{label_text}}} {value:g} [{scope}]")
    if len(lines) == 1:
        lines.append("  （无直方图数据）")
    return lines


def render_human(snap: MetricsSnapshot) -> str:
    lines: list[str] = []
    lines.append(
        f"=== LangGraph 指标快照 · {snap.timestamp} · host={snap.host} ==="
    )
    lines.append("")
    lines.extend(_render_http_section(snap.counters))
    lines.append("")
    lines.extend(_render_histogram_section(snap.counters))
    lines.append("")
    lines.extend(_render_node_section(snap.counters))
    lines.append("")
    lines.extend(_render_business_section(snap.counters))
    lines.append("")
    lines.extend(_render_canary_section(snap.counters))
    lines.append("")
    lines.extend(_render_health_section(snap.counters))
    return "\n".join(lines)


def render_json(snap: MetricsSnapshot) -> str:
    """机器可读输出：name → list[{labels, value}]"""
    data: dict[str, Any] = {
        "timestamp": snap.timestamp,
        "host": snap.host,
        "counters": {},
    }
    for name, by_labels in snap.counters.items():
        data["counters"][name] = [
            {"labels": dict(labels), "value": value}
            for labels, value in sorted(by_labels.items())
        ]
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_snapshot(metrics_url: str) -> MetricsSnapshot:
    text = _fetch_metrics(metrics_url)
    counters = _parse_metrics(text)
    return MetricsSnapshot(
        timestamp=strftime("%Y-%m-%d %H:%M:%S"),
        host=urlparse(metrics_url).hostname or "<unknown>",
        counters=counters,
    )


def cli() -> int:
    parser = argparse.ArgumentParser(
        description="LangGraph 全指标快照（灰度期运维 CLI）"
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/metrics",
        help="LangGraph /metrics endpoint",
    )
    parser.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    args = parser.parse_args()

    snap = build_snapshot(args.url)
    print(render_json(snap) if args.json else render_human(snap))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
