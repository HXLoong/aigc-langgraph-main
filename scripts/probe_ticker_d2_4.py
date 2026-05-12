#!/usr/bin/env python3
"""D2.4 ticker 真 GOATS 联调端到端验证（Issue #76）。

3 个模式：
    --case <raw>      跑单个 case 看 resolver 输出 + 主图 HITL 信号
    --hitl-flow       完整 HITL 两轮交互：先发"中国平安看涨期权"看消歧卡片，
                      再发"选 1"模拟用户回复看 ticker 是否被填上
    --fixture         跑全套 34 条 ticker fixture，输出 PASS rate（D2.4 退出门 ≥ 90%）

不触发 write endpoint（绝不下单），仅 read GOATS。

使用：
    python scripts/probe_ticker_d2_4.py --case "中国平安"
    python scripts/probe_ticker_d2_4.py --hitl-flow
    python scripts/probe_ticker_d2_4.py --fixture
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path


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
        print(f"    - {c.windCode}  ({c.insShtDesc})  from_goats={c.from_goats}  score={c.relevanceScore}")
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
    print(f"  tickers:               {[t.windCode for t in result1.get('tickers') or []]}")
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
    print(f"  tickers:               {[t.windCode for t in result2.get('tickers') or []]}")
    print(f"  ticker_hitl_candidates:{len(result2.get('ticker_hitl_candidates') or [])}")
    print(f"  reply_text 摘要:        {(result2.get('reply_text') or '')[:120]!r}")
    return 0


# ============================================================
# 模式 3：34 条 ticker fixture 真后端 PASS rate
# ============================================================


async def run_fixture() -> int:
    from app.subgraphs.ticker.resolver import resolve_ticker_full
    from app.subgraphs.ticker.tools import tokenize

    path = Path("tests/fixtures/golden_ticker_2026-05.jsonl")
    if not path.exists():
        print(f"fixture not found: {path}", file=sys.stderr)
        return 2

    cases = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    print(f"=== ticker fixture 真后端跑 {len(cases)} 条 ===")

    stats = Counter()
    fails: list[tuple[str, str, dict, dict]] = []
    by_cat = Counter()
    pass_by_cat = Counter()

    for case in cases:
        cid = case["id"]
        raw = case["raw_content"]
        expected = case["expected"]
        category = case["category"]
        by_cat[category] += 1

        actual: dict = {}
        try:
            actual["tokens"] = tokenize.invoke({"raw_text": raw})
        except Exception as exc:  # noqa: BLE001
            actual["tokens_err"] = f"{type(exc).__name__}: {exc}"

        try:
            resolution = await resolve_ticker_full(raw)
            resolved_codes = [c.windCode for c in resolution.resolved]
            needs_hitl = bool(resolution.hitl_pending)
            winner = resolved_codes[0] if resolved_codes else None
            actual["winner"] = winner
            actual["needs_hitl"] = needs_hitl
        except Exception as exc:  # noqa: BLE001
            actual["resolve_err"] = f"{type(exc).__name__}: {exc}"

        # 判定：winner + needs_hitl 一致即 PASS（tokens 不强检，因为已有 32 条 tokenize 单测）
        ok = (
            actual.get("winner") == expected.get("winner")
            and actual.get("needs_hitl") == expected.get("needs_hitl")
        )
        if ok:
            stats["pass"] += 1
            pass_by_cat[category] += 1
        else:
            stats["fail"] += 1
            fails.append((cid, raw, expected, actual))

    total = stats["pass"] + stats["fail"]
    pct = 100.0 * stats["pass"] / total if total else 0.0

    print(f"\nPASS: {stats['pass']}/{total} = {pct:.1f}% (D2.4 退出门 ≥ 90%)\n")
    print("按 category:")
    for cat, n in sorted(by_cat.items()):
        p = pass_by_cat[cat]
        print(f"  {cat:<40} {p}/{n}")

    if fails:
        print(f"\n失败 {len(fails)} 条：")
        for cid, raw, exp, act in fails[:10]:
            print(f"  {cid:<8} raw={raw[:30]!r:<32}")
            print(f"           expected winner={exp.get('winner')} needs_hitl={exp.get('needs_hitl')}")
            print(f"           actual   winner={act.get('winner')} needs_hitl={act.get('needs_hitl')}  err={act.get('resolve_err') or '-'}")
        if len(fails) > 10:
            print(f"  ... 还有 {len(fails) - 10} 条")

    return 0 if pct >= 90.0 else 1


# ============================================================
# CLI
# ============================================================


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default=None, help="单 case raw_text")
    parser.add_argument("--hitl-flow", action="store_true", help="HITL 两轮模拟")
    parser.add_argument("--fixture", action="store_true", help="跑 ticker fixture 全集")
    args = parser.parse_args()

    if args.case:
        return asyncio.run(run_case(args.case))
    if args.hitl_flow:
        return asyncio.run(run_hitl_flow())
    if args.fixture:
        return asyncio.run(run_fixture())

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(cli())
