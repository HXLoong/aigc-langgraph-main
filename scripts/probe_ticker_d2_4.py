#!/usr/bin/env python3
"""D2.4 ticker 真 GOATS 联调端到端验证（Issue #76）。

2 个模式：
    --case <raw>      跑单个 case 看 resolver 输出 + 主图 HITL 信号
    --hitl-flow       完整 HITL 两轮交互：先发"中国平安看涨期权"看消歧卡片，
                      再发"选 1"模拟用户回复看 ticker 是否被填上

不触发 write endpoint（绝不下单），仅 read GOATS。

使用：
    python scripts/probe_ticker_d2_4.py --case "中国平安"
    python scripts/probe_ticker_d2_4.py --hitl-flow
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time


# ============================================================
# 模式 1：单 case resolver 探测
# ============================================================


async def run_case(raw_text: str) -> int:
    from app.subgraphs.ticker.resolver import resolve_ticker_full

    t0 = time.monotonic()
    resolution = await resolve_ticker_full(raw_text)
    lat = int((time.monotonic() - t0) * 1000)

    print(f"=== ticker.resolve_ticker_full · raw={raw_text!r} ===")
    print(f"  latency:        {lat}ms")
    print(f"  resolved:       {len(resolution.resolved)}")
    for c in resolution.resolved[:5]:
        print(f"    - {c.wind_code}  ({c.ins_sht_desc})  from_goats={c.from_goats}  score={c.relevance_score}")
    print(f"  hitl_pending:   {len(resolution.hitl_pending)}")
    for item in resolution.hitl_pending:
        print(f"    keyword={item['keyword']!r}  candidates={len(item['candidates'])}")
        for c in item["candidates"][:5]:
            print(f"      · {c.get('windCode')}  {c.get('insShtDesc')}  score={c.get('relevanceScore')}")
    return 0


# ============================================================
# 模式 2：HITL 完整两轮流程（直接 invoke 主图，不起 uvicorn）
# ============================================================


async def run_hitl_flow() -> int:
    """模拟企微多命中 HITL 完整两轮：
    第一轮：用户问 "中国平安看涨期权" → 多命中 → 消歧卡片
    第二轮：用户回复 "中国平安保险" → 单命中 → ticker 填上
    """
    from app.graph.main import build_main_graph

    graph = build_main_graph()  # 无 checkpointer，单次 invoke

    # 第一轮 · 多命中触发 HITL
    print("=== 第一轮 · 用户问 '中国平安看涨期权'（多命中触发 HITL）===")
    state1: dict = {
        "raw_text": "中国平安看涨期权",
        "conversation_id": "test-hitl-1",
        "user_id": "u1",
        "room_id": "r1",
    }
    t0 = time.monotonic()
    result1 = await graph.ainvoke(state1)
    lat1 = int((time.monotonic() - t0) * 1000)
    hitl1 = result1.get("ticker_hitl_candidates") or []
    print(f"  latency:               {lat1}ms")
    print(f"  product_type:          {result1.get('product_type')}")
    print(f"  intent:                {result1.get('intent')}")
    print(f"  tickers:               {[t.wind_code for t in result1.get('tickers') or []]}")
    print(f"  ticker_hitl_candidates:{len(hitl1)} group(s)")
    for group in hitl1:
        print(f"    keyword={group['keyword']!r}  候选 {len(group['candidates'])} 条")
        for c in group["candidates"][:3]:
            print(f"      · {c.get('windCode')}  {c.get('insShtDesc')}")
    print(f"  reply_text 摘要:        {(result1.get('reply_text') or '')[:120]!r}")
    if not hitl1:
        print("  ⚠️ 未触发 HITL，可能 GOATS 命中分差 ≥ RANK_AUTO_PICK_GAP=10")

    # 第二轮 · 用户消歧后完整名（"中国平安保险"应该单命中）
    print("\n=== 第二轮 · 用户回复 '中国平安看涨期权 选第一个'（消歧）===")
    state2: dict = {
        "raw_text": "中国平安看涨期权 选第一个",
        "conversation_id": "test-hitl-1",
        "user_id": "u1",
        "room_id": "r1",
    }
    t0 = time.monotonic()
    result2 = await graph.ainvoke(state2)
    lat2 = int((time.monotonic() - t0) * 1000)
    print(f"  latency:               {lat2}ms")
    print(f"  product_type:          {result2.get('product_type')}")
    print(f"  intent:                {result2.get('intent')}")
    print(f"  tickers:               {[t.wind_code for t in result2.get('tickers') or []]}")
    print(f"  ticker_hitl_candidates:{len(result2.get('ticker_hitl_candidates') or [])}")
    print(f"  reply_text 摘要:        {(result2.get('reply_text') or '')[:120]!r}")
    return 0


# ============================================================
# CLI
# ============================================================


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default=None, help="单 case raw_text")
    parser.add_argument("--hitl-flow", action="store_true", help="HITL 两轮模拟")
    args = parser.parse_args()

    if args.case:
        return asyncio.run(run_case(args.case))
    if args.hitl_flow:
        return asyncio.run(run_hitl_flow())

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(cli())
