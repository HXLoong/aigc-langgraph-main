#!/usr/bin/env python3
"""真后端 E2E probe runner · 切流前最后一道真后端保障。

整合互换 / 期权 / 平仓写路径与标的相关消息的真后端探针：

- 统一参数：--target swap|option|close|ticker|all
- 强制校验 EVAL_USER_ID / EVAL_ROOM_ID（避免污染生产业务流）
- 标准化输出：.harness-runs/probe-{timestamp}/{summary.json + report.md}
- 失败时可选推 webhook（与 alerts.py 复用同一通道）

跑法：
    python scripts/probe_real_backend_e2e.py --target all
    python scripts/probe_real_backend_e2e.py --target swap --case 0
    python scripts/probe_real_backend_e2e.py --target option --report-only
    python scripts/probe_real_backend_e2e.py --target all --webhook-on-fail

退出码：
    0 全部 case 无 exception（含 business reject）
    1 至少一条 case uncaught exception
    2 前置失败（EVAL_* 未配置 / 命令行参数错）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 让脚本能直接运行
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ============================================================
# CASES 库（按 target 划分 · 风险从低到高排列）
# ============================================================


@dataclass(frozen=True)
class ProbeCase:
    id: str
    target: str  # swap / option / close / ticker
    raw_text: str
    notes: str
    expected_intent: str | None = None


# 注：CASES 顺序必须从安全（read）→ 不可逆 副作用（write/place）排列。
# 单步失败建议立即停止后续（--stop-on-fail）。
CASES: list[ProbeCase] = [
    # swap（互换）：3 条
    ProbeCase("swap-query-01", "swap",
              "查一下 互换 我的订单状态",
              "query_order_status · 最安全 · 仅读语义",
              "query_order_status"),
    ProbeCase("swap-cancel-01", "swap",
              "撤掉互换订单 H-20260101-NONEXIST",
              "cancel_order_request · 撤不存在订单 → 业务拒绝（不创建数据）",
              "cancel_order_request"),
    ProbeCase("swap-place-01", "swap",
              "互换下单 贵州茅台 100 股 限价 1800",
              "place_order_request · 最小金额下单（仅在客户授权后执行）",
              "place_order_request"),
    # option（期权）：3 条
    ProbeCase("opt-query-01", "option",
              "查一下期权 我的订单状态",
              "query_order_status · read 类",
              "query_order_status"),
    ProbeCase("opt-cancel-01", "option",
              "撤掉期权订单 OPT-NONEXIST",
              "cancel_order_request · 撤不存在",
              "cancel_order_request"),
    ProbeCase("opt-inquiry-01", "option",
              "参与型看涨 腾讯控股 1个月",
              "new_inquiry · 询价（read 语义，不产生订单）",
              "new_inquiry"),
    # close（期权平仓）：4 条
    ProbeCase("close-holding-01", "close",
              "我有什么期权持仓",
              "holding_query · read 持仓",
              "holding_query"),
    ProbeCase("close-query-01", "close",
              "查我的平仓订单",
              "query_close_orders · read",
              "query_status"),
    ProbeCase("close-confirm-cancel-01", "close",
              "确认取消平仓 NONEXIST",
              "confirm_cancel · 撤不存在 → 业务拒绝",
              "confirm_cancel"),
    ProbeCase("close-confirm-place-01", "close",
              "确认平仓 NONEXIST",
              "confirm_close · 平不存在 → 业务拒绝",
              "confirm_close"),
    # ticker（标的）：3 条（仅 read endpoint，无 write 风险）
    ProbeCase("tk-single-01", "ticker",
              "贵州茅台",
              "单命中 → 600519.SH"),
    ProbeCase("tk-multi-01", "ticker",
              "中国平安",
              "多命中 → 触发 HITL 信号"),
    ProbeCase("tk-unknown-01", "ticker",
              "完全不存在的 xyz 标的",
              "0 命中 → 白名单兜底或空结果"),
]


# ============================================================
# 单 case 执行
# ============================================================


@dataclass
class ProbeResult:
    case_id: str
    target: str
    raw_text: str
    notes: str
    latency_ms: int = 0
    status: str = "unknown"  # ok / business_reject / unreachable / exception
    api_code: int | None = None
    intent: str | None = None
    error_message: str | None = None
    reply_text_preview: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "target": self.target,
            "raw_text": self.raw_text,
            "notes": self.notes,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "api_code": self.api_code,
            "intent": self.intent,
            "error_message": self.error_message,
            "reply_text_preview": self.reply_text_preview,
            **{k: v for k, v in self.extra.items()},
        }


def _classify_status(state: dict[str, Any], exception: Exception | None) -> str:
    if exception is not None:
        # 区分 unreachable vs 其他 exception
        name = type(exception).__name__
        if name == "BackendUnreachableError":
            return "unreachable"
        return "exception"
    err = state.get("error")
    if err is not None:
        err_type = err.type if hasattr(err, "type") else err.get("type", "")
        if err_type == "BackendUnreachableError":
            return "unreachable"
        return "exception"
    api_code = state.get("api_code")
    if api_code is None:
        # 无后端调用（如 ticker 子图只 read）→ 按 reply_text 是否含 fallback 判定
        reply = state.get("reply_text") or ""
        if "没完全理解" in reply or "抱歉" in reply:
            return "exception"
        return "ok"
    return "ok" if api_code == 0 else "business_reject"


async def run_case(case: ProbeCase, graph: Any) -> ProbeResult:
    """单 case 真后端 e2e。"""
    from app.config import get_settings

    settings = get_settings()
    convo = f"probe-{int(time.time())}-{case.id}-{uuid.uuid4().hex[:6]}"
    state: dict[str, Any] = {
        "raw_text": case.raw_text,
        "conversation_id": convo,
        "message_id": int(time.time() * 1000),
        "user_id": settings.eval_user_id,
        "room_id": settings.eval_room_id,
    }

    t0 = time.monotonic()
    exception: Exception | None = None
    final: dict[str, Any] = {}
    try:
        final = await graph.ainvoke(state)
    except Exception as exc:  # noqa: BLE001
        exception = exc
    latency = int((time.monotonic() - t0) * 1000)
    status = _classify_status(final, exception)

    err = final.get("error")
    err_msg: str | None = None
    if err is not None:
        msg = err.message if hasattr(err, "message") else err.get("message", "")
        err_msg = str(msg)[:200] if msg else None
    elif exception is not None:
        err_msg = f"{type(exception).__name__}: {exception}"[:200]

    return ProbeResult(
        case_id=case.id,
        target=case.target,
        raw_text=case.raw_text,
        notes=case.notes,
        latency_ms=latency,
        status=status,
        api_code=final.get("api_code"),
        intent=final.get("intent"),
        error_message=err_msg,
        reply_text_preview=(final.get("reply_text") or "")[:200] or None,
        extra={
            "product_type": final.get("product_type"),
            "conversation_id": convo,
        },
    )


# ============================================================
# 报告渲染
# ============================================================


def summarize(results: list[ProbeResult]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    by_target: dict[str, dict[str, int]] = {}
    for r in results:
        slot = by_target.setdefault(r.target, {})
        slot[r.status] = slot.get(r.status, 0) + 1
    total = len(results)
    ok_count = by_status.get("ok", 0) + by_status.get("business_reject", 0)
    return {
        "total": total,
        "by_status": by_status,
        "by_target": by_target,
        # 通过率：ok + business_reject 都算"链路通"（business_reject 是后端按业务规则拒绝，链路本身工作）
        "pass_rate": (ok_count / total) if total else 0.0,
        "has_failure": by_status.get("exception", 0) > 0,
    }


def render_markdown(results: list[ProbeResult], summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# 真后端 E2E probe 报告 · {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"- 总 case 数: {summary['total']}")
    lines.append(f"- 通过率（含 business_reject）: {summary['pass_rate']:.1%}")
    lines.append(f"- 状态分布: `{summary['by_status']}`")
    lines.append("")
    lines.append("## 按 target 分类")
    lines.append("")
    lines.append("| target | ok | business_reject | unreachable | exception |")
    lines.append("|---|---|---|---|---|")
    for target in sorted(summary["by_target"]):
        s = summary["by_target"][target]
        lines.append(
            f"| {target} | {s.get('ok', 0)} | {s.get('business_reject', 0)} | "
            f"{s.get('unreachable', 0)} | {s.get('exception', 0)} |"
        )
    lines.append("")
    lines.append("## case 详情")
    lines.append("")
    lines.append("| case | target | latency | status | api_code | intent | notes |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        icon = {
            "ok": "✅", "business_reject": "🟡", "unreachable": "🔴", "exception": "❌"
        }.get(r.status, "?")
        lines.append(
            f"| `{r.case_id}` | {r.target} | {r.latency_ms}ms | "
            f"{icon} {r.status} | {r.api_code if r.api_code is not None else '-'} | "
            f"{r.intent or '-'} | {r.notes} |"
        )
    failures = [r for r in results if r.status in ("exception", "unreachable")]
    if failures:
        lines.append("")
        lines.append("## 失败详情")
        lines.append("")
        for r in failures:
            lines.append(f"### {r.case_id}")
            lines.append("")
            lines.append(f"- raw: `{r.raw_text}`")
            lines.append(f"- status: {r.status}")
            if r.error_message:
                lines.append(f"- error: `{r.error_message}`")
            if r.reply_text_preview:
                lines.append(f"- reply: {r.reply_text_preview}")
            lines.append("")
    return "\n".join(lines)


# ============================================================
# 输出 + webhook
# ============================================================


def write_outputs(
    results: list[ProbeResult], summary: dict[str, Any], out_dir: Path
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "summary": summary,
                "results": [r.to_dict() for r in results],
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    report_path = out_dir / "report.md"
    report_path.write_text(render_markdown(results, summary), encoding="utf-8")
    return summary_path, report_path


def maybe_send_webhook(summary: dict[str, Any], report_path: Path) -> None:
    """probe 有 exception → 推企微告警群（复用 alerts.py 通道）。"""
    if not summary["has_failure"]:
        return
    webhook = os.environ.get("WECHAT_ALERT_WEBHOOK_URL", "")
    if not webhook:
        print("INFO: WECHAT_ALERT_WEBHOOK_URL 未配置，跳过 webhook 推送")
        return
    msg = (
        f"🚨 **真后端 probe 失败** [P1]\n\n"
        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"通过率: {summary['pass_rate']:.1%}\n"
        f"状态分布: `{summary['by_status']}`\n\n"
        f"报告: {report_path}\n"
        f"参考: docs/on-call-runbook.md §5.4（Java 后端不可达）"
    )
    try:
        from app.observability.alerts import send_wechat_webhook
        send_wechat_webhook(msg, webhook)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: webhook 推送失败: {type(exc).__name__}")


# ============================================================
# 主流程
# ============================================================


def filter_cases(target: str) -> list[ProbeCase]:
    if target == "all":
        return list(CASES)
    return [c for c in CASES if c.target == target]


async def _amain(args: argparse.Namespace) -> int:
    # 前置校验
    from app.config import get_settings
    settings = get_settings()
    if not args.report_only:
        # report-only 跑无 EVAL 也允许（仅看历史报告）
        if not settings.eval_user_id or not settings.eval_room_id:
            print(
                "ERROR: EVAL_USER_ID / EVAL_ROOM_ID 未配置（避免污染生产业务流）。\n"
                "       请在 .env 设置（参考 .env.customer.template §12）。",
                file=sys.stderr,
            )
            return 2

    cases = filter_cases(args.target)
    if args.case is not None:
        if not (0 <= args.case < len(cases)):
            print(f"ERROR: --case 索引越界（0 ~ {len(cases) - 1}）", file=sys.stderr)
            return 2
        cases = [cases[args.case]]

    if not cases:
        print(f"ERROR: target={args.target} 无 case", file=sys.stderr)
        return 2

    print(f"=== 真后端 E2E probe · target={args.target} · {len(cases)} cases ===\n")

    if args.report_only:
        print("(--report-only) 跳过实跑")
        results: list[ProbeResult] = []
    else:
        from app.graph.main import build_main_graph
        graph = build_main_graph()
        results = []
        for case in cases:
            print(f"--- {case.id} · {case.raw_text!r} ---")
            print(f"    notes: {case.notes}")
            r = await run_case(case, graph)
            results.append(r)
            print(f"    [{r.latency_ms:>5}ms] status={r.status} "
                  f"api_code={r.api_code} intent={r.intent or '-'}")
            if r.error_message:
                print(f"    error: {r.error_message}")
            print()
            if args.stop_on_fail and r.status in ("exception", "unreachable"):
                print("--stop-on-fail · 立即停止后续 case")
                break

    summary = summarize(results)

    # 输出 .harness-runs/probe-{ts}/
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = PROJECT_ROOT / ".harness-runs" / f"probe-{ts}"
    if results:
        sum_path, rep_path = write_outputs(results, summary, out_dir)
        print(f"=== 退出门 ===")
        print(f"  total cases    : {summary['total']}")
        print(f"  pass rate      : {summary['pass_rate']:.1%}")
        print(f"  status         : {summary['by_status']}")
        print()
        print(f"  summary: {sum_path}")
        print(f"  report:  {rep_path}")

        if args.webhook_on_fail and summary["has_failure"]:
            maybe_send_webhook(summary, rep_path)

    return 1 if summary.get("has_failure") else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="真后端 E2E probe runner（切流前真后端保障）"
    )
    parser.add_argument(
        "--target",
        choices=["swap", "option", "close", "ticker", "all"],
        default="all",
        help="probe target，默认 all",
    )
    parser.add_argument(
        "--case", type=int, default=None,
        help="按索引只跑某条 case（0-based，相对 --target 过滤后的列表）",
    )
    parser.add_argument(
        "--stop-on-fail", action="store_true",
        help="任一 case status=exception/unreachable 立即停止后续",
    )
    parser.add_argument(
        "--webhook-on-fail", action="store_true",
        help="失败时推 WECHAT_ALERT_WEBHOOK_URL（与 alerts.py 同通道）",
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="不实跑，只校验参数 + 显示 cases 列表（CI dry-run / 验证 .env）",
    )
    args = parser.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
