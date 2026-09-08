#!/usr/bin/env python3
"""Run LangGraph regression cases and optionally push the report to WeCom."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from wecom_report_support import (
    build_markdown_summary,
    load_dotenv,
    load_json_report,
    push_report,
    resolve_report,
    resolve_webhook,
)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
LANGGRAPH_SCRIPT = SCRIPT_DIR / "langgraph_direct_regression.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="运行 LangGraph 回归，并将汇总和 Markdown 附件推送到企微"
    )
    parser.add_argument("--report", type=Path, help="只处理已有 Markdown 报告")
    parser.add_argument("--wecom-timeout", type=float, default=15.0)
    parser.add_argument("--upload-timeout", type=float, default=180.0)
    parser.add_argument("--wecom-retries", type=int, default=2)
    parser.add_argument("--wecom-insecure", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def run_regression(regression_args: Sequence[str]) -> tuple[int, Path]:
    blocked = {"--no-report", "--dry-run", "--list", "--self-test"}
    if any(value.split("=", 1)[0] in blocked for value in regression_args):
        raise ValueError("企微报告链路不允许关闭报告或改变执行模式")
    process = subprocess.Popen(
        [sys.executable, "-u", str(LANGGRAPH_SCRIPT), *regression_args],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    reports: list[Path] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        if line.startswith("Markdown report: "):
            reports.append(Path(line.removeprefix("Markdown report: ").strip()))
    return_code = process.wait()
    if not reports:
        raise ValueError(
            f"LangGraph 测试脚本退出码为 {return_code}，但未生成 Markdown 报告"
        )
    return return_code, resolve_report(reports[-1])


def run_self_test() -> int:
    command_ok = LANGGRAPH_SCRIPT.is_file()
    print(f"[{'PASS' if command_ok else 'FAIL'}] LangGraph 回归脚本存在")
    return 0 if command_ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = build_parser()
    args, regression_args = parser.parse_known_args(argv)
    if args.self_test:
        return run_self_test()
    try:
        if args.report is not None and regression_args:
            raise ValueError("使用 --report 时不能再指定 LangGraph 测试参数")
        if args.wecom_timeout <= 0 or args.upload_timeout <= 0:
            raise ValueError("企微超时必须大于 0")
        if args.wecom_retries < 0:
            raise ValueError("企微重试次数不能小于 0")
        return_code = 0
        if args.report is not None:
            report = resolve_report(args.report)
        else:
            return_code, report = run_regression(regression_args)
        summary = build_markdown_summary(report, load_json_report(report))
        summary = summary.replace("Dify Test Report", "LangGraph Test Report")
        print("\n--- 企微 Markdown 预览 ---")
        print(summary)
        print("--- 预览结束 ---\n")
        if not args.send:
            print("预览完成：未推送企微；确认后添加 --send")
            return return_code
        results = push_report(
            resolve_webhook(),
            report,
            summary,
            timeout=args.wecom_timeout,
            upload_timeout=args.upload_timeout,
            retries=args.wecom_retries,
            insecure=args.wecom_insecure,
        )
        failed = any(not result or result.get("errcode") != 0 for result in results)
        return 2 if failed else return_code
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
