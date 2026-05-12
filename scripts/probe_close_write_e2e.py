#!/usr/bin/env python3
"""D2.1 follow-up · close.operate 真后端 write 端到端验证（Issue #80）。

按风险从低到高跑：
1. close_holding_query "我的持仓" → close_order_query (read 类)
2. close_query_status "查询平仓订单 CO-XXX" → close_order_order_query (read 类)
3. close_confirm_cancel "确认撤销平仓 CO-NONEXIST" → close_order_cancel_confirm (write，但订单不存在 → 业务拒绝)
4. close_confirm_close "确认平仓 CO-NONEXIST" → close_order_confirm (write，但订单不存在 → 业务拒绝)

所有 case 用 EVAL_USER_ID / EVAL_ROOM_ID 测试隔离账号。
确认类用**不存在的订单号**，确保不产生真实副作用。

使用：
    python scripts/probe_close_write_e2e.py
    python scripts/probe_close_write_e2e.py --case 0
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from typing import Any

CASES: list[dict[str, str]] = [
    {
        "id": "close-holding-01",
        "raw_text": "我的持仓",
        "notes": "close_holding_query → close_order_query · read 类，最安全",
    },
    {
        "id": "close-query-01",
        "raw_text": "查询平仓订单 CO-20260101-NONEXIST 的状态",
        "notes": "close_query_status → close_order_order_query · read 类（订单不存在）",
    },
    {
        "id": "close-confirm-cancel-01",
        "raw_text": "确认撤销平仓 CO-20260101-NONEXIST",
        "notes": "close_confirm_cancel → close_order_cancel_confirm · write，订单不存在 → 业务拒绝",
    },
    {
        "id": "close-confirm-close-01",
        "raw_text": "确认平仓 CO-20260101-NONEXIST",
        "notes": "close_confirm_close → close_order_confirm · write，订单不存在 → 业务拒绝",
    },
]


def _summarize(state: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "product_type": state.get("product_type"),
        "intent": state.get("intent"),
        "api_code": state.get("api_code"),
    }
    api_result = state.get("api_result")
    if api_result is not None:
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
    close = state.get("close_params")
    if close:
        summary["close_params_keys"] = list(close.keys())[:10]
    confirm = state.get("confirm")
    if confirm:
        summary["confirm_action"] = confirm.get("action")
        summary["confirm_order_count"] = len(
            confirm.get("confirmOrderNoList") or confirm.get("confirmCancelOrderNoList") or []
        )
    query = state.get("query_filter")
    if query:
        summary["query_filter_keys"] = list(query.keys())[:10]
    summary["reply_text_preview"] = (state.get("reply_text") or "")[:200]
    return summary


async def run_case(case: dict[str, str], graph) -> dict[str, Any]:
    from app.config import get_settings

    settings = get_settings()
    if not settings.eval_room_id or not settings.eval_user_id:
        raise RuntimeError("EVAL_ROOM_ID / EVAL_USER_ID 未配置")

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
        summary = _summarize(result)
        summary["latency_ms"] = lat
        summary["case_id"] = case["id"]
        summary["raw_text"] = case["raw_text"]
        return summary
    except Exception as exc:  # noqa: BLE001
        return {
            "case_id": case["id"],
            "raw_text": case["raw_text"],
            "exception": f"{type(exc).__name__}: {exc}",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }


async def main(case_filter: int | None) -> int:
    from app.graph.main import build_main_graph

    graph = build_main_graph()
    selected = CASES if case_filter is None else [CASES[case_filter]]

    print(f"=== Issue #80 close.operate 端到端 · {len(selected)} 条 case ===\n")
    results: list[dict[str, Any]] = []
    for case in selected:
        print(f"--- {case['id']} · {case['raw_text']!r} ---")
        print(f"    notes: {case['notes']}")
        summary = await run_case(case, graph)
        results.append(summary)
        for k in (
            "latency_ms",
            "product_type",
            "intent",
            "api_code",
            "close_params_keys",
            "confirm_action",
            "confirm_order_count",
            "query_filter_keys",
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

    n_ok = sum(1 for r in results if r.get("api_code") == 0)
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

    print("=== 退出门 ===")
    print(f"  total cases       : {len(results)}")
    print(f"  api_code=0 (ok)   : {n_ok}")
    print(f"  api_code!=0       : {n_business_reject}")
    print(f"  BackendUnreachable: {n_unreachable}")
    print(f"  uncaught exception: {n_exception}")

    return 0 if n_exception == 0 else 1


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int, default=None)
    args = parser.parse_args()
    return asyncio.run(main(args.case))


if __name__ == "__main__":
    sys.exit(cli())
