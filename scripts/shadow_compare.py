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
    """从 Dify 工作流响应中提取完整 outputs（F4.1 字段级 diff）。

    Dify 标准响应：{data: {outputs: {...}, status: "succeeded"}}

    F4.1 增强：除 product_type / intent / api_code 外，也提取业务对象字段：
    - tickers（标的解析结果）
    - place_params / cancel_params / confirm / query_filter / close_params
    - ticker_hitl_candidates（HITL 卡片）
    - reply_text（最终回复）
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
        "tickers": outputs.get("tickers") or [],
        "place_params": outputs.get("place_params") or outputs.get("placeParams") or {},
        "cancel_params": outputs.get("cancel_params") or outputs.get("cancelParams") or {},
        "confirm": outputs.get("confirm") or {},
        "query_filter": outputs.get("query_filter") or outputs.get("queryFilter") or {},
        "close_params": outputs.get("close_params") or outputs.get("closeParams") or {},
        "ticker_hitl_candidates": outputs.get("ticker_hitl_candidates")
        or outputs.get("tickerHitlCandidates")
        or [],
        "reply_text": outputs.get("reply_text") or outputs.get("replyText"),
    }


def _normalize_langgraph(lg_resp: dict) -> dict:
    """LangGraph 响应是 Dify 协议（ADR 0001 D3 完全模拟 Dify Workflow Run API）。"""
    return _normalize_dify(lg_resp)


# F4.1 字段级 diff 配置：随机字段默认忽略（订单号 / UUID / 时间戳 / 延迟敏感字段）
DEFAULT_IGNORED_PATHS = frozenset(
    {
        # 订单号在两侧独立生成（H-/OPT-/CO- prefix 后是 timestamp + random）
        "*.orderId",
        "*.orderNo",
        "*.workflow_run_id",
        "*.task_id",
        "*.id",
        # 时间戳
        "*.created_at",
        "*.finished_at",
        "*.timestamp",
        # reply_text 是渲染层，按 ADR 0017 不强 diff（业务方按业务对象 review）
        "reply_text",
    }
)


def _flatten(obj, prefix: str = "") -> dict[str, object]:
    """把嵌套 dict / list 摊平为 path → value 字典。

    用于业务对象字段级 diff：
    - {"orderList": [{"qty": 100}]} → {"orderList[0].qty": 100}
    """
    out: dict[str, object] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _path_matches(path: str, ignore_patterns: set[str]) -> bool:
    """检查 path 是否被忽略 pattern 匹配。`*.foo` 匹配任何后缀为 .foo 的 path。"""
    for pat in ignore_patterns:
        if pat == path:
            return True
        if pat.startswith("*."):
            suffix = pat[1:]  # 包含开头的点
            if path.endswith(suffix):
                return True
            # *.foo 也匹配纯 foo（无前缀）
            if path == pat[2:]:
                return True
    return False


def compare(
    lg_resp: dict,
    dify_resp: dict,
    ignore_paths: set[str] | None = None,
) -> tuple[bool, dict]:
    """对比两侧归一化输出，按字段路径产出 diff。

    Args:
        lg_resp / dify_resp: HTTP 响应原始字典
        ignore_paths: 忽略的字段 path 集合（支持 `*.foo` 通配后缀）。
            None 表示用 DEFAULT_IGNORED_PATHS。

    Returns:
        (is_equal, diffs)：is_equal = True 表示无 diff；
        diffs 是 path → {langgraph, dify} 字典。
    """
    ignore = ignore_paths if ignore_paths is not None else set(DEFAULT_IGNORED_PATHS)

    lg_norm = _normalize_langgraph(lg_resp)
    dify_norm = _normalize_dify(dify_resp)

    lg_flat = _flatten(lg_norm)
    dify_flat = _flatten(dify_norm)

    diffs: dict = {}
    all_paths = set(lg_flat.keys()) | set(dify_flat.keys())
    for path in sorted(all_paths):
        if _path_matches(path, ignore):
            continue
        lg_val = lg_flat.get(path)
        dify_val = dify_flat.get(path)
        if lg_val != dify_val:
            diffs[path] = {"langgraph": lg_val, "dify": dify_val}

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


def write_markdown_report(
    path: Path, results: list[CompareResult], summary: Summary
) -> None:
    """生成 F4.1 每日 diff 报告（业务方 review 用）。

    格式：摘要 + 按字段 diff Top-K + 失败 case 列表（含 raw_content）。
    """
    diff_rate = summary.diff / max(summary.total, 1)
    lines: list[str] = []
    lines.append(f"# Shadow 对比报告 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 总 case | {summary.total} |")
    lines.append(f"| 等价 (equal) | {summary.equal} |")
    lines.append(f"| 差异 (diff) | {summary.diff} |")
    lines.append(f"| 错误 (error) | {summary.error} |")
    lines.append(f"| **差异率** | **{diff_rate:.1%}** |")
    lines.append("")

    if summary.by_field:
        lines.append("## 差异字段分布（Top 10）")
        lines.append("")
        lines.append("| 字段路径 | 差异 case 数 |")
        lines.append("|---|---|")
        top = sorted(summary.by_field.items(), key=lambda kv: -kv[1])[:10]
        for fld, n in top:
            lines.append(f"| `{fld}` | {n} |")
        lines.append("")

    diffed = [r for r in results if not r.is_equal and not r.error]
    if diffed:
        lines.append(f"## 差异 case（共 {len(diffed)} 条，展示前 20）")
        lines.append("")
        for r in diffed[:20]:
            lines.append(f"### `{r.case_id}` · {r.raw_content[:60]}")
            lines.append("")
            lines.append("| 字段 | LangGraph | Dify |")
            lines.append("|---|---|---|")
            for fld, vals in list(r.diffs.items())[:8]:
                lg_v = str(vals.get("langgraph"))[:60]
                df_v = str(vals.get("dify"))[:60]
                lines.append(f"| `{fld}` | `{lg_v}` | `{df_v}` |")
            lines.append("")
        if len(diffed) > 20:
            lines.append(f"_…还有 {len(diffed) - 20} 条差异 case 未展示，详见 JSON 报告_")
            lines.append("")

    errored = [r for r in results if r.error]
    if errored:
        lines.append(f"## 错误 case（共 {len(errored)} 条）")
        lines.append("")
        for r in errored[:10]:
            lines.append(f"- `{r.case_id}` · {r.raw_content[:50]}: {r.error[:100]}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


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

    # trust_env=False 跳过系统代理（macOS scutil --proxy 配置会让 httpx 把
    # localhost 请求路由到 127.0.0.1:1082 等代理 → 503）。
    # 真 Dify 在公网时如需走代理，按需注入 mounts={"https://": httpx.AsyncHTTPTransport(proxy=...)}
    async with httpx.AsyncClient(trust_env=False) as client:
        for i, case in enumerate(cases, 1):
            inputs = {
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

            # ADR 0001 D3: LangGraph 完全模拟 Dify Workflow Run API
            # → 两边请求体结构一致 {inputs, user, response_mode}
            shared_payload = {
                "inputs": inputs,
                "user": f"shadow-{case['id']}",
                "response_mode": "blocking",
            }

            (lg_resp, lg_lat), (dify_resp, dify_lat) = await asyncio.gather(
                call_endpoint(client, args.langgraph, shared_payload),
                call_endpoint(client, args.dify, shared_payload, headers=dify_headers),
            )

            ignore_paths = set(DEFAULT_IGNORED_PATHS) | set(args.ignore_field or [])
            is_equal, diffs = compare(lg_resp, dify_resp, ignore_paths=ignore_paths)
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

    # F4.1 markdown 每日报告
    if args.markdown_report and not args.dry_run:
        write_markdown_report(args.markdown_report, results, summary)
        print(f"Markdown 报告已写入 {args.markdown_report}")

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
    parser.add_argument("--markdown-report", type=Path, default=None,
                        help="F4.1 每日 diff 报告 markdown 路径（业务方 review 用）")
    parser.add_argument("--ignore-field", action="append", default=[],
                        help="忽略字段 path（可多次指定，支持 *.foo 通配）")
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
