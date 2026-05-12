#!/usr/bin/env python3
"""真后端 ticker 子图端到端验证（D2.1）。

只触发 read endpoints（ticker.select + counterparty.inference_prompt + LLM）。
不触发 write endpoints（不会真下单）。

跑几个典型 case：
- 单命中：贵州茅台 → 应解析为 600519.SH
- 多命中：中国平安 → 应触发 HITL 信号
- 0 命中：随机串 → 应走白名单兜底或返回空

输出每个 case：
- 用时
- resolved 列表（标的代码 + 简称）
- hitl_pending 列表

使用：
    python scripts/probe_ticker_e2e.py
"""
from __future__ import annotations

import asyncio
import sys
import time


async def _run_one(raw_text: str) -> None:
    from app.subgraphs.ticker.resolver import resolve_ticker_full

    t0 = time.monotonic()
    try:
        resolution = await resolve_ticker_full(raw_text)
    except Exception as exc:  # noqa: BLE001
        latency = int((time.monotonic() - t0) * 1000)
        print(f"[{latency:>5}ms] raw={raw_text!r:<30} → ERROR: {type(exc).__name__}: {exc}")
        return
    latency = int((time.monotonic() - t0) * 1000)
    resolved_summary = ", ".join(
        f"{c.windCode}({c.insShtDesc})" for c in resolution.resolved[:3]
    )
    if len(resolution.resolved) > 3:
        resolved_summary += f", ...({len(resolution.resolved)} total)"
    hitl_summary = (
        f"HITL[{len(resolution.hitl_pending)}]" if resolution.hitl_pending else ""
    )
    print(
        f"[{latency:>5}ms] raw={raw_text!r:<30} → resolved=[{resolved_summary or '∅'}] {hitl_summary}"
    )


async def main() -> int:
    cases = [
        "请帮我查一下贵州茅台的报价",
        "茅台",
        "600519",
        "中国平安",
        "工商银行 看涨期权",
        "asdf随便一个串zxcv",
    ]
    print("=== ticker 子图真后端端到端探测 ===")
    for raw in cases:
        await _run_one(raw)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
