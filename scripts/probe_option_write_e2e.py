#!/usr/bin/env python3
"""D2.1 + D2.2 真后端 write endpoint 端到端验证（option 询价，最低风险 write）。

按 ADR 0016 灰度顺序，option.operate type=new_inquiry 在客户后端**生成询价记录**，
不是真订单——但仍是 write endpoint，会留下数据库行。

使用 EVAL_* 测试账号（隔离测试空间，客户已授权）：
    EVAL_USER_ID / EVAL_ROOM_ID  在 .env 配置

跑 3 类代表性 case：
1. 询价：贵州茅台 看涨期权 1个月 行权价 1800
2. 询价：阿里巴巴 看跌期权 3个月 行权价 70
3. 询价：腾讯 雪球 6个月 敲入 70% 敲出 100%

每条 case 端到端：
    raw_text → 主图 → option_intent → option_extract_inquiry
        → call_option_backend(真 endpoint) → render
        ↓
    输出 final_state.api_code / api_result / 字段对齐报告

绝不下单（type=new_inquiry 不是 place_order_from_quote），不触发任何 confirm。

使用：
    python scripts/probe_option_write_e2e.py
    python scripts/probe_option_write_e2e.py --case 0   # 仅跑第一条
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Any

CASES: list[dict[str, str]] = [
    {
        "id": "opt-write-01",
        "raw_text": "贵州茅台 欧式看涨期权 1个月 行权价 1800",
        "notes": "A 股询价 · 简单参数 · 期望 LLM 提取 标的=600519.SH / type=call / tenor=1M / strike=1800",
    },
    {
        "id": "opt-write-02",
        "raw_text": "阿里巴巴 欧式看跌期权 3个月 行权价 70",
        "notes": "港股询价 · 标的=09988.HK / type=put / tenor=3M / strike=70",
    },
    {
        "id": "opt-write-03",
        "raw_text": "腾讯 雪球 6个月 敲入 70% 敲出 100%",
        "notes": "雪球询价 · 标的=00700.HK / 敲入敲出参数",
    },
]


def _summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    """提取 final state 中端到端关键字段（不含全量 trace/raw payload）。"""
    summary: dict[str, Any] = {
        "product_type": state.get("product_type"),
        "intent": state.get("intent"),
        "api_code": state.get("api_code"),
    }
    tickers = state.get("tickers") or []
    summary["tickers"] = [
        {
            "windCode": getattr(t, "windCode", None) or (t.get("windCode") if isinstance(t, dict) else None),
            "insShtDesc": getattr(t, "insShtDesc", None) or (t.get("insShtDesc") if isinstance(t, dict) else None),
            "from_goats": getattr(t, "from_goats", None) or (t.get("from_goats") if isinstance(t, dict) else None),
        }
        for t in tickers[:3]
    ]
    place = state.get("place_params") or {}
    summary["place_params_expected_action"] = place.get("expected_action")
    orders = place.get("orderList") or []
    summary["place_params_order_count"] = len(orders)
    if orders:
        # 只 dump 第一条订单的关键字段（避免冗长）
        o = orders[0]
        summary["place_params_first_order"] = {
            k: o.get(k)
            for k in ("stockCode", "optionType", "tenor", "strikePercentage", "strikePrice")
            if o.get(k) is not None
        }
    api_result = state.get("api_result")
    if api_result is not None:
        # 真后端响应 data —— 只取 type / 关键字段，避免完整 dump
        if isinstance(api_result, dict):
            summary["api_result_keys"] = list(api_result.keys())[:10]
        elif isinstance(api_result, str):
            summary["api_result_str"] = api_result[:200]
        else:
            summary["api_result_type"] = type(api_result).__name__
    err = state.get("error")
    if err is not None:
        summary["error"] = {
            "type": err.type if hasattr(err, "type") else err.get("type"),
            "node": err.node if hasattr(err, "node") else err.get("node"),
            "message": (err.message if hasattr(err, "message") else err.get("message"))[:200],
        }
    summary["reply_text_preview"] = (state.get("reply_text") or "")[:200]
    return summary


async def run_case(case: dict[str, str], graph) -> dict[str, Any]:
    from app.config import get_settings

    settings = get_settings()
    if not settings.eval_room_id or not settings.eval_user_id:
        raise RuntimeError(
            "EVAL_ROOM_ID / EVAL_USER_ID 未配置；请在 .env 设置测试隔离账号"
        )

    # 用唯一 conversation_id，避免不同 case 状态污染
    convo = f"probe-d2-{int(time.time())}-{case['id']}-{uuid.uuid4().hex[:6]}"

    state: dict[str, Any] = {
        "raw_text": case["raw_text"],
        "conversation_id": convo,
        "message_id": int(time.time() * 1000),
        "user_id": settings.eval_user_id,
        "room_id": settings.eval_room_id,
    }

    t0 = time.monotonic()
    try:
        result = await graph.ainvoke(state)
        lat = int((time.monotonic() - t0) * 1000)
        summary = _summarize_state(result)
        summary["latency_ms"] = lat
        summary["case_id"] = case["id"]
        summary["raw_text"] = case["raw_text"]
        summary["conversation_id"] = convo
        return summary
    except Exception as exc:  # noqa: BLE001
        lat = int((time.monotonic() - t0) * 1000)
        return {
            "case_id": case["id"],
            "raw_text": case["raw_text"],
            "conversation_id": convo,
            "latency_ms": lat,
            "exception": f"{type(exc).__name__}: {exc}",
        }


async def main(case_filter: int | None) -> int:
    from app.graph.main import build_main_graph

    graph = build_main_graph()  # 无 checkpointer，单次 invoke

    selected = CASES if case_filter is None else [CASES[case_filter]]

    print(f"=== D2.1 + D2.2 option write 端到端 · {len(selected)} 条 case ===\n")
    results: list[dict[str, Any]] = []
    for case in selected:
        print(f"--- {case['id']} · {case['raw_text']!r} ---")
        print(f"    notes: {case['notes']}")
        summary = await run_case(case, graph)
        results.append(summary)
        # 紧凑输出
        for k in (
            "latency_ms",
            "product_type",
            "intent",
            "api_code",
            "tickers",
            "place_params_expected_action",
            "place_params_first_order",
            "api_result_keys",
            "api_result_str",
            "error",
            "reply_text_preview",
        ):
            v = summary.get(k)
            if v is not None:
                print(f"    {k}: {v}")
        if summary.get("exception"):
            print(f"    ❌ EXCEPTION: {summary['exception']}")
        print()

    # 退出门统计
    n_5xx = 0  # 真 5xx 会被 D2.3 翻译成 BackendUnreachableError，error.type 检查
    n_4xx = 0
    n_business_reject = sum(
        1
        for r in results
        if r.get("api_code") is not None and r.get("api_code") != 0
    )
    n_exception = sum(1 for r in results if r.get("exception"))
    n_unreachable = sum(
        1
        for r in results
        if r.get("error") and r["error"].get("type") == "BackendUnreachableError"
    )
    n_ok = sum(1 for r in results if r.get("api_code") == 0)

    print("=== 退出门 ===")
    print(f"  total cases       : {len(results)}")
    print(f"  api_code=0 (ok)   : {n_ok}")
    print(f"  api_code!=0       : {n_business_reject}")
    print(f"  BackendUnreachable: {n_unreachable}")
    print(f"  uncaught exception: {n_exception}")
    print(f"  D2.* 退出门要求：5xx=0 / 4xx=0 / 业务拒绝有 fallback / unreachable=0")
    print()

    return 0 if n_exception == 0 else 1


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int, default=None, help="仅跑某条 case 的 index")
    args = parser.parse_args()
    return asyncio.run(main(args.case))


if __name__ == "__main__":
    sys.exit(cli())
