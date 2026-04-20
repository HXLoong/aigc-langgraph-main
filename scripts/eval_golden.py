#!/usr/bin/env python3
"""在 golden set 上评估 LangGraph 端到端准确率。

用法：
    python scripts/eval_golden.py tests/fixtures/golden.jsonl

输出：
    总数 / 通过数 / 失败详情 / 按 category 分组的准确率
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx


async def run_one_case(
    client: httpx.AsyncClient, case: dict, endpoint: str,
) -> dict:
    """发送一条 case 到 /v1/message 并对比 expected。"""
    payload = {
        "conversation_id": f"eval-{case['id']}",
        "message_id": f"m-{case['id']}",
        "room_id": "eval-room",
        "user_id": "eval-user",
        "guid": "",
        "raw_content": case["raw_content"],
        "quote_content": case.get("quote_content"),
    }
    start = time.monotonic()
    try:
        r = await client.post(endpoint, json=payload, timeout=60.0)
        r.raise_for_status()
        resp = r.json()
    except Exception as e:
        return {
            "id": case["id"],
            "passed": False,
            "reason": f"HTTP 错误: {e}",
            "duration_ms": int((time.monotonic() - start) * 1000),
        }

    latency = int((time.monotonic() - start) * 1000)
    expected = case["expected"]

    diffs = []
    # 比对 product_type
    if "product_type" in expected and resp.get("product_type") != expected["product_type"]:
        diffs.append(
            f"product_type: 期望={expected['product_type']} 实际={resp.get('product_type')}"
        )
    # 比对 intent
    if "intent" in expected and resp.get("intent") != expected["intent"]:
        diffs.append(
            f"intent: 期望={expected['intent']} 实际={resp.get('intent')}"
        )

    return {
        "id": case["id"],
        "category": case.get("category", "unknown"),
        "passed": not diffs,
        "reason": "; ".join(diffs) if diffs else "ok",
        "duration_ms": latency,
        "response": resp,
    }


async def main(golden_path: Path, endpoint: str, parallel: int):
    with open(golden_path, encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]

    print(f"加载 {len(cases)} 条 golden case")
    print(f"目标端点：{endpoint}")
    print(f"并发：{parallel}\n")

    async with httpx.AsyncClient() as client:
        sem = asyncio.Semaphore(parallel)

        async def wrap(case):
            async with sem:
                return await run_one_case(client, case, endpoint)

        results = await asyncio.gather(*[wrap(c) for c in cases])

    # 汇总
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n========== 总结 ==========")
    print(f"通过: {passed}/{total}  准确率: {passed/total*100:.1f}%")

    avg_latency = sum(r["duration_ms"] for r in results) / total
    p95 = sorted(r["duration_ms"] for r in results)[int(total * 0.95)]
    print(f"平均延迟: {avg_latency:.0f}ms  P95: {p95}ms")

    # 按 category
    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)

    print(f"\n========== 按分类 ==========")
    for cat, rs in sorted(by_cat.items()):
        p = sum(1 for r in rs if r["passed"])
        print(f"  {cat}: {p}/{len(rs)} ({p/len(rs)*100:.0f}%)")

    # 失败详情
    failed = [r for r in results if not r["passed"]]
    if failed:
        print(f"\n========== 失败详情 ==========")
        for r in failed:
            print(f"  [{r['id']}] {r['category']}: {r['reason']}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("golden_path", type=Path,
                        help="JSONL 文件，每行一个 case")
    parser.add_argument("--endpoint", default="http://localhost:8000/v1/message")
    parser.add_argument("--parallel", type=int, default=5)
    args = parser.parse_args()

    asyncio.run(main(args.golden_path, args.endpoint, args.parallel))
