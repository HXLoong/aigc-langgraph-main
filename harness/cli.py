"""Harness CLI — `python -m harness <cmd>`（ADR 0014 D5）。

子命令：
- run [--category <prefix>] [--out <dir>]     跑 case，输出 JSON + markdown 报告
- eval                                         (M2) 在 LangFuse Dataset 上跑评估
- diff <run-a> <run-b>                         (M3) 比对 shadow 双跑
- sync-golden                                  (M2) golden.jsonl ↔ LangFuse Dataset 同步
- promote-prompt <name>                        (D3) 从 LangFuse 演练区晋升到 git
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from harness.differ import diff_fields, is_pass
from harness.golden import filter_by_category, filter_by_ids, load_golden
from harness.reporter import (
    render_markdown,
    summarize,
    write_failure_json,
)
from harness.runner import run_case

logger = logging.getLogger(__name__)


DEFAULT_GOLDEN_PATHS = [
    Path("tests/fixtures/golden.jsonl"),
]
# option_golden.jsonl 是业务 QA schema（含 conversation 数组），M1 不直接消费


# ============================================================
# run
# ============================================================


async def cmd_run(args: argparse.Namespace) -> int:
    # --mock-ticker 强制走白名单（CI / 离线场景）
    if getattr(args, "mock_ticker", False):
        import os
        os.environ["TICKER_RESOLVER_MODE"] = "whitelist"
        # 重置已加载的模块状态
        import importlib
        import app.subgraphs.ticker.resolver as _res_mod
        _res_mod.DEFAULT_MODE = "whitelist"
        print("  [mock-ticker] TICKER_RESOLVER_MODE=whitelist")

    cases = []
    for p in DEFAULT_GOLDEN_PATHS:
        cases.extend(load_golden(p))
    if not cases:
        print("ERROR: no golden cases found", file=sys.stderr)
        return 2

    case_ids: list[str] | None = args.case if args.case else None
    cases = filter_by_ids(cases, case_ids)
    cases = filter_by_category(cases, args.category)
    if not cases:
        filter_desc = f"case={case_ids!r}" if case_ids else f"category={args.category!r}"
        print(f"ERROR: no cases match {filter_desc}", file=sys.stderr)
        return 2

    print(f"running {len(cases)} cases ...")

    results: list[tuple[Any, list[Any]]] = []
    for case in cases:
        r = await run_case(case)
        diffs = diff_fields(case.expected, r.final_state)
        results.append((r, diffs))
        marker = "PASS" if is_pass(diffs) else "FAIL"
        print(f"  [{marker}] {case.id} ({case.category})")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 写每条失败 case 的 JSON 报告
    failures_dir = out_dir / "failures"
    for r, diffs in results:
        if not is_pass(diffs):
            write_failure_json(r, diffs, failures_dir)

    # 写汇总
    s = summarize(results)
    (out_dir / "summary.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "summary.md").write_text(render_markdown(results), encoding="utf-8")

    print()
    print(
        f"PASS: {s['passed']} / FAIL: {s['failed']} / TOTAL: {s['total']} "
        f"(pass rate: {s['pass_rate']:.1%})"
    )
    print(f"reports → {out_dir}")
    return 0 if s["failed"] == 0 else 1


# ============================================================
# stub for M2/M3
# ============================================================


def cmd_stub(name: str) -> int:
    print(f"`{name}` is a stub for M2/M3 (not implemented in M1).", file=sys.stderr)
    return 64


# ============================================================
# entry
# ============================================================


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="跑 golden case")
    run.add_argument(
        "--all", action="store_true", help="跑所有 case（与 --category 互斥）"
    )
    run.add_argument(
        "--case",
        action="append",
        metavar="ID",
        default=None,
        help="按 case ID 精确过滤，可多次指定（如 --case g042 --case g001）",
    )
    run.add_argument(
        "--category", default=None, help="按 category 前缀过滤（如 swap/place_order）"
    )
    run.add_argument(
        "--out",
        default=".harness-runs/latest",
        help="报告输出目录（默认 .harness-runs/latest）",
    )
    run.add_argument(
        "--mock-ticker",
        action="store_true",
        default=False,
        help="强制 ticker resolver 走白名单模式（CI / 离线 / --mock-ticker）",
    )

    sub.add_parser("eval", help="(M2) LangFuse Dataset 上跑评估")
    diff = sub.add_parser("diff", help="(M3) shadow 双跑比对")
    diff.add_argument("run_a")
    diff.add_argument("run_b")
    sub.add_parser("sync-golden", help="(M2) golden ↔ LangFuse Dataset")
    pp = sub.add_parser("promote-prompt", help="(ADR 0014 D3) 从 LangFuse 晋升到 git")
    pp.add_argument("name")

    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "run":
        return asyncio.run(cmd_run(args))
    if args.cmd in ("eval", "sync-golden"):
        return cmd_stub(args.cmd)
    if args.cmd == "diff":
        return cmd_stub("diff")
    if args.cmd == "promote-prompt":
        return cmd_stub("promote-prompt")
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
