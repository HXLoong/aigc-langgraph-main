#!/usr/bin/env python3
"""Shadow 双跑：同时请求 LangGraph 和 Dify，对比差异。

用于灰度切换期的差异监控，回答"LangGraph 是否能等价替代 Dify"。

## 用法

```bash
# 最小用法（差异打印到 stdout，明细写入 JSON 文件）
python scripts/shadow_compare.py \\
    --langgraph http://localhost:8000/v1/message \\
    --dify https://dify.example.com/v1/workflows/run \\
    --dify-api-key dify-app-xxx \\
    --sample tests/fixtures/golden.jsonl \\
    --output /tmp/shadow_diff.json

# 同时写入 MySQL（生产灰度场景）
python scripts/shadow_compare.py \\
    --langgraph ... --dify ... --sample ... \\
    --mysql-host mysql.prod \\
    --mysql-db otc_agent_business

# Dry-run（只打印不存盘）
python scripts/shadow_compare.py ... --dry-run

# 只跑前 N 条
python scripts/shadow_compare.py ... --max-cases 5
```

## 响应归一化

- LangGraph 返回 `{product_type, intent, api_code, ...}`
- Dify 工作流返回 `{data: {outputs: {...}}}` — 由 _normalize_dify() 提取
  product_type / intent 字段。如果你的 Dify 工作流输出字段名不同，调整该函数。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

try:
    import aiomysql  # type: ignore
    HAS_AIOMYSQL = True
except ImportError:
    HAS_AIOMYSQL = False


# ============================================================
# 数据结构
# ============================================================
@dataclass
class CompareResult:
    case_id: str
    raw_content: str
    is_equal: bool
    diffs: dict
    langgraph_resp: dict
    dify_resp: dict
    langgraph_latency_ms: int
    dify_latency_ms: int
    error: str = ""


@dataclass
class Summary:
    total: int = 0
    equal: int = 0
    diff: int = 0
    error: int = 0
    by_field: dict[str, int] = field(default_factory=dict)


# ============================================================
# 端点调用
# ============================================================
async def call_endpoint(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    headers: dict | None = None,
    timeout: float = 60.0,
) -> tuple[dict, int]:
    """调用 HTTP 端点，返回 (响应字典, 延迟毫秒)。"""
    import time
    start = time.monotonic()
    try:
        r = await client.post(url, json=payload, headers=headers, timeout=timeout)
        latency = int((time.monotonic() - start) * 1000)
        try:
            body = r.json()
        except Exception:
            body = {"_raw": r.text[:500]}
        return ({"status": r.status_code, "body": body}, latency)
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        return ({"status": -1, "body": {"error": str(e)}}, latency)


def _normalize_dify(dify_resp: dict) -> dict:
    """从 Dify 工作流响应中提取 product_type / intent / api_code。

    Dify 标准响应：{data: {outputs: {...}, status: "succeeded"}}
    工作流的 outputs 是字典，约定包含 product_type / intent 字段。
    如果你的 Dify 工作流输出字段名不同，按需调整这里。
    """
    body = dify_resp.get("body") or {}
    outputs = (body.get("data") or {}).get("outputs") or {}

    # 兼容 Dify outputs 直接有 / 嵌套在 result 内的两种约定
    if isinstance(outputs.get("result"), dict):
        outputs = {**outputs, **outputs["result"]}

    return {
        "product_type": outputs.get("product_type") or outputs.get("productType"),
        "intent": outputs.get("intent"),
        "api_code": outputs.get("api_code") or outputs.get("apiCode"),
    }


def _normalize_langgraph(lg_resp: dict) -> dict:
    """LangGraph 响应已经是扁平字段，直接抽出对比维度。"""
    body = lg_resp.get("body") or {}
    return {
        "product_type": body.get("product_type"),
        "intent": body.get("intent"),
        "api_code": body.get("api_code"),
    }


def compare(lg_resp: dict, dify_resp: dict) -> tuple[bool, dict]:
    """对比两侧的归一化字段。"""
    lg_norm = _normalize_langgraph(lg_resp)
    dify_norm = _normalize_dify(dify_resp)

    diffs: dict = {}
    for key in ("product_type", "intent", "api_code"):
        if lg_norm.get(key) != dify_norm.get(key):
            diffs[key] = {"langgraph": lg_norm.get(key), "dify": dify_norm.get(key)}

    return (not diffs, diffs)


# ============================================================
# 输出 sink
# ============================================================
async def write_to_mysql(pool: Any, result: CompareResult) -> None:
    """写一条对比记录到 shadow_compare 表。"""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO shadow_compare
                (message_id, primary_path, primary_result, shadow_result,
                 is_equal, diff_detail, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    result.case_id,
                    "langgraph",
                    json.dumps(result.langgraph_resp, ensure_ascii=False),
                    json.dumps(result.dify_resp, ensure_ascii=False),
                    1 if result.is_equal else 0,
                    json.dumps(result.diffs, ensure_ascii=False),
                    datetime.now(),
                ),
            )
            await conn.commit()


def write_to_file(path: Path, results: list[CompareResult], summary: Summary) -> None:
    """把所有结果 + 汇总写到 JSON 文件。"""
    data = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total": summary.total,
            "equal": summary.equal,
            "diff": summary.diff,
            "error": summary.error,
            "diff_rate": round(summary.diff / max(summary.total, 1), 4),
            "diff_by_field": summary.by_field,
        },
        "results": [
            {
                "case_id": r.case_id,
                "raw_content": r.raw_content,
                "is_equal": r.is_equal,
                "diffs": r.diffs,
                "langgraph_latency_ms": r.langgraph_latency_ms,
                "dify_latency_ms": r.dify_latency_ms,
                "langgraph_normalized": _normalize_langgraph(r.langgraph_resp),
                "dify_normalized": _normalize_dify(r.dify_resp),
                "error": r.error,
            }
            for r in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 主流程
# ============================================================
async def main(args: argparse.Namespace) -> int:
    cases = [json.loads(line) for line in args.sample.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.max_cases:
        cases = cases[: args.max_cases]
    print(f"加载 {len(cases)} 条 case  |  LangGraph={args.langgraph}  |  Dify={args.dify}")

    # MySQL 池（可选）
    pool = None
    if args.mysql_host and not args.dry_run:
        if not HAS_AIOMYSQL:
            print("WARN: aiomysql 未安装，跳过 MySQL 写入", file=sys.stderr)
        else:
            pool = await aiomysql.create_pool(
                host=args.mysql_host, port=args.mysql_port,
                user=args.mysql_user, password=args.mysql_password,
                db=args.mysql_db, autocommit=False,
            )

    summary = Summary(total=len(cases))
    results: list[CompareResult] = []
    dify_headers = {"Authorization": f"Bearer {args.dify_api_key}"} if args.dify_api_key else None

    async with httpx.AsyncClient() as client:
        for i, case in enumerate(cases, 1):
            payload = {
                "conversation_id": f"shadow-{case['id']}",
                "message_id": f"shadow-m-{case['id']}",
                "room_id": "shadow-room",
                "user_id": "shadow-user",
                "guid": "",
                "raw_content": case["raw_content"],
                "quote_content": case.get("quote_content"),
                "quote_appinfo": case.get("quote_appinfo"),
                "attachments": case.get("attachments", []),
            }

            # Dify 工作流通常需要包一层 inputs
            dify_payload = {
                "inputs": payload,
                "user": "shadow-compare",
                "response_mode": "blocking",
            }

            (lg_resp, lg_lat), (dify_resp, dify_lat) = await asyncio.gather(
                call_endpoint(client, args.langgraph, payload),
                call_endpoint(client, args.dify, dify_payload, headers=dify_headers),
            )

            is_equal, diffs = compare(lg_resp, dify_resp)
            err = ""
            if lg_resp.get("status", -1) < 0:
                err = f"langgraph_unreachable: {lg_resp['body'].get('error', '')}"
                summary.error += 1
            elif dify_resp.get("status", -1) < 0:
                err = f"dify_unreachable: {dify_resp['body'].get('error', '')}"
                summary.error += 1
            elif is_equal:
                summary.equal += 1
            else:
                summary.diff += 1
                for field_name in diffs:
                    summary.by_field[field_name] = summary.by_field.get(field_name, 0) + 1

            result = CompareResult(
                case_id=case["id"],
                raw_content=case["raw_content"],
                is_equal=is_equal,
                diffs=diffs,
                langgraph_resp=lg_resp,
                dify_resp=dify_resp,
                langgraph_latency_ms=lg_lat,
                dify_latency_ms=dify_lat,
                error=err,
            )
            results.append(result)

            # 实时打印
            if err:
                mark = "!"
            elif is_equal:
                mark = "✓"
            else:
                mark = "✗"
            short_diff = ", ".join(
                f"{k}=lg:{v['langgraph']}/df:{v['dify']}" for k, v in diffs.items()
            ) or err
            print(f"[{i:03d}/{len(cases)}] {mark} {case['id']:<6}  lg={lg_lat}ms df={dify_lat}ms  {short_diff}")

            # 写 MySQL（可选）
            if pool and not err:
                await write_to_mysql(pool, result)

    if pool:
        pool.close()
        await pool.wait_closed()

    # 输出文件
    if args.output and not args.dry_run:
        write_to_file(args.output, results, summary)
        print(f"\n详细结果已写入 {args.output}")

    # 汇总
    print(f"\n{'='*60}")
    print(f"  Total: {summary.total}  Equal: {summary.equal}  Diff: {summary.diff}  Error: {summary.error}")
    print(f"  差异率: {summary.diff / max(summary.total - summary.error, 1) * 100:.1f}%")
    if summary.by_field:
        print(f"  差异按字段: {summary.by_field}")
    print(f"{'='*60}")

    # 发布门槛：差异率 ≤ 1% 才返回 0（适合 CI 集成）
    if args.fail_threshold is not None:
        diff_rate = summary.diff / max(summary.total - summary.error, 1)
        if diff_rate > args.fail_threshold:
            print(f"差异率 {diff_rate:.4f} > 阈值 {args.fail_threshold}，FAIL", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LangGraph vs Dify shadow 双跑对比")
    parser.add_argument("--langgraph", required=True, help="LangGraph /v1/message 端点 URL")
    parser.add_argument("--dify", required=True, help="Dify /v1/workflows/run 端点 URL")
    parser.add_argument("--dify-api-key", default="", help="Dify App API Key（写入 Authorization 头）")
    parser.add_argument("--sample", required=True, type=Path, help="JSONL 样本文件路径")
    parser.add_argument("--output", type=Path, default=None, help="JSON 输出路径（明细 + 汇总）")
    parser.add_argument("--max-cases", type=int, default=0, help="只跑前 N 条（0 = 全跑）")
    parser.add_argument("--dry-run", action="store_true", help="不写文件、不写 MySQL")
    parser.add_argument("--fail-threshold", type=float, default=None,
                        help="差异率阈值（如 0.01 = 1%%）；超过则进程返回非零退出码")

    parser.add_argument("--mysql-host", default="", help="留空 = 不写 MySQL")
    parser.add_argument("--mysql-port", type=int, default=3306)
    parser.add_argument("--mysql-user", default="otc_agent")
    parser.add_argument("--mysql-password", default="password")
    parser.add_argument("--mysql-db", default="otc_agent_business")

    sys.exit(asyncio.run(main(parser.parse_args())))
