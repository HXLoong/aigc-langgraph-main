#!/usr/bin/env python3
"""金丝雀切流状态查询（运维工具）。

业务方/Tony 在金丝雀阶段查"当前 LangGraph 收到了什么流量"+ "是否合规"。

跑法：
    python scripts/canary_status.py                     # 默认从本地 /metrics 拉
    python scripts/canary_status.py --url http://prod:8000/metrics
    python scripts/canary_status.py --json              # 机器可读输出

输出（人读模式）：
    === 金丝雀切流状态 · {timestamp} ===
    Allowlist (CANARY_ROOM_IDS):     2 roomId（r-test-1, r-test-2）
    模式:                            部分群阶段
    canary 流量累计:                  142
    非 canary 流量累计:                0  ✅
    退出门检查:
      非 canary 流量 = 0              ✅ 退出门要求
      P0 误切告警:                    未触发

如果非 canary 流量 > 0：
- 立刻告诉 Tony，让企微管理员把该 roomId 的 Webhook 切回 Dify
- 触发 P0 告警（alerts.py non_canary_traffic）
- 误切样本数 = 输出里 "非 canary 流量累计"

退出码：
    0  正常（非 canary 流量 == 0 或 ALL 模式）
    1  发现非 canary 流量（说明有 webhook 误切）
    2  无法访问 /metrics endpoint
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from time import strftime
from urllib.parse import urlparse

import httpx


@dataclass
class CanaryStatus:
    timestamp: str
    metrics_url_host: str
    allowlist: list[str]
    mode: str  # "未启用" / "部分群阶段" / "ALL 全量"
    canary_count: int
    non_canary_count: int
    dry_run_intercept: int = 0  # otc_agent_dry_run_intercept_total 汇总（shadow 护栏）

    @property
    def total(self) -> int:
        return self.canary_count + self.non_canary_count

    @property
    def is_breach(self) -> bool:
        """部分灰度：non_canary>0 即违规；ALL 全量：dry_run 拦截>0 即违规。

        2026-08-27 裁决：ALL（全量）+ DRY_RUN_BACKEND 仍在拦截写请求 = 配置错误
        （业务写操作被悄悄丢弃），runbook §5 的 P0 护栏由此成真。
        """
        if "ALL" in self.allowlist:
            return self.dry_run_intercept > 0
        return self.non_canary_count > 0


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


def _parse_canary_counters(metrics_text: str) -> tuple[int, int]:
    """从 prometheus exposition 解析 otc_agent_canary_traffic_total 两个 label。

    Returns:
        (canary_count, non_canary_count)
    """
    canary = 0
    non_canary = 0
    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("otc_agent_canary_traffic_total"):
            continue
        # otc_agent_canary_traffic_total{is_canary="true"} 142
        try:
            _, rest = line.split("{", 1)
            labels_str, value_str = rest.split("}", 1)
            value = int(float(value_str.strip()))
        except (ValueError, IndexError):
            continue
        if 'is_canary="true"' in labels_str:
            canary += value
        elif 'is_canary="false"' in labels_str:
            non_canary += value
    return canary, non_canary


def _parse_dry_run_intercept(metrics_text: str) -> int:
    """汇总 otc_agent_dry_run_intercept_total 所有 label 组合的计数。"""
    total = 0
    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("otc_agent_dry_run_intercept_total"):
            continue
        try:
            value = int(float(line.rsplit(" ", 1)[1]))
        except (ValueError, IndexError):
            continue
        total += value
    return total


def _describe_mode(allowlist: list[str]) -> str:
    if not allowlist:
        return "未启用（金丝雀关）"
    if "ALL" in allowlist:
        return "ALL 全量上线"
    n = len(allowlist)
    if n <= 2:
        return f"部分群阶段（{n} 个群）"
    return f"多群阶段（{n} 个群）"


def build_status(metrics_url: str) -> CanaryStatus:
    from app.observability.canary import get_canary_room_ids

    metrics_text = _fetch_metrics(metrics_url)
    canary_count, non_canary_count = _parse_canary_counters(metrics_text)
    dry_run_intercept = _parse_dry_run_intercept(metrics_text)
    allowlist = sorted(get_canary_room_ids())
    host = urlparse(metrics_url).hostname or "<unknown>"

    return CanaryStatus(
        timestamp=strftime("%Y-%m-%d %H:%M:%S"),
        metrics_url_host=host,
        allowlist=allowlist,
        mode=_describe_mode(allowlist),
        canary_count=canary_count,
        non_canary_count=non_canary_count,
        dry_run_intercept=dry_run_intercept,
    )


def render_human(s: CanaryStatus) -> str:
    lines: list[str] = []
    lines.append(f"=== 金丝雀切流状态 · {s.timestamp} ===")
    lines.append(f"metrics endpoint host:           {s.metrics_url_host}")
    lines.append(
        f"Allowlist (CANARY_ROOM_IDS):     {len(s.allowlist)} roomId"
        + (f"（{', '.join(s.allowlist)}）" if s.allowlist else "")
    )
    lines.append(f"模式:                            {s.mode}")
    lines.append(f"canary 流量累计:                  {s.canary_count}")

    breach_mark = "❌" if s.is_breach else "✅"
    lines.append(f"非 canary 流量累计:                {s.non_canary_count}  {breach_mark}")
    lines.append("")
    lines.append("退出门检查:")
    if "ALL" in s.allowlist and s.is_breach:
        lines.append(
            f"  ⚠️  全量模式下 dry_run 拦截 = {s.dry_run_intercept} > 0 → "
            "DRY_RUN_BACKEND 仍在丢弃写请求！立即检查 .env 配置（runbook §5 / P0）"
        )
    elif "ALL" in s.allowlist:
        lines.append("  全量模式，无需检查非 canary 流量（dry_run 拦截 = 0 ✅）")
    elif s.is_breach:
        lines.append(
            f"  ⚠️  非 canary 流量 = {s.non_canary_count} > 0 → "
            "有 Webhook 误切！请立即让企微管理员回切非 canary 群的 Webhook 到 Dify"
        )
        lines.append("  对应 P0 告警: non_canary_traffic（alerts.py）")
    else:
        lines.append("  ✅ 非 canary 流量 = 0  退出门达标")
    return "\n".join(lines)


def cli() -> int:
    parser = argparse.ArgumentParser(
        description="金丝雀切流状态查询"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/metrics",
        help="LangGraph /metrics endpoint",
    )
    parser.add_argument(
        "--json", action="store_true", help="机器可读 JSON 输出"
    )
    args = parser.parse_args()

    status = build_status(args.url)

    if args.json:
        print(
            json.dumps(
                {
                    "timestamp": status.timestamp,
                    "metrics_url_host": status.metrics_url_host,
                    "allowlist": status.allowlist,
                    "mode": status.mode,
                    "canary_count": status.canary_count,
                    "non_canary_count": status.non_canary_count,
                    "is_breach": status.is_breach,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_human(status))

    return 1 if status.is_breach else 0


if __name__ == "__main__":
    sys.exit(cli())
