"""Command line entry point for biz-based HTTP regression."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from harness.golden import (
    file_group,
    load_golden,
    select_by_ids,
    select_dataset_files,
)
from harness.http_evaluation import DEFAULT_BASE_URL, ensure_app_available, run_case
from harness.langfuse_client import flush
from harness.node_registry import DEFAULT_NODE_REGISTRY
from harness.node_runner import (
    NodeFixtureSkipError,
    NodeRunnerError,
    load_node_fixtures,
    run_node_fixture,
    run_node_fixture_http,
)
from harness.run_reports import RunReports

_REQUIRED_SERVER_MODE = {"mock": "real", "java": "real"}


def _backend_gate(backend: str | None, server_mode: str | None) -> str | None:
    """保留 doctor 对显式服务模式的兼容检查。"""
    if backend is None:
        return None
    wanted = _REQUIRED_SERVER_MODE[backend]
    if server_mode is not None and server_mode != wanted:
        return f"--backend {backend} needs server backend_mode={wanted}, but /health reports {server_mode!r}"
    return None


async def _doctor(base_url: str, checkpoint: str = "none", backend: str | None = None) -> int:
    """核对本地应用、持久化与后端模式是否满足所选评测要求。"""
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10.0) as client:
        try:
            health = await client.get("/health")
            ready = await client.get("/ready")
        except httpx.HTTPError as exc:
            print(f"ERROR: uvicorn unavailable: {exc}", file=sys.stderr)
            return 2
    print(f"base_url={base_url}")
    print(f"health={health.status_code}")
    print(f"ready={ready.status_code} {ready.text[:500]}")
    if not health.is_success:
        return 2
    try:
        server_mode = health.json().get("backend_mode")
    except ValueError:
        server_mode = None
    reason = _backend_gate(backend, server_mode)
    if reason:
        print(f"ERROR: {reason}", file=sys.stderr)
        return 2
    if ready.is_success:
        return 0
    if checkpoint == "none":
        try:
            checks = ready.json().get("checks", {})
        except ValueError:
            return 2
        non_checkpoint_failures = {
            name: status for name, status in checks.items() if name != "mysql" and status == "fail"
        }
        return 0 if not non_checkpoint_failures else 2
    return 2


def _resolve_eval_ids(user_id: str | None, room_id: str | None) -> tuple[str, str]:
    """身份使用统一 Settings，环境变量优先于 .env。"""
    from app.config import get_settings

    settings = get_settings()
    return user_id or settings.eval_user_id, room_id or settings.eval_room_id


async def _run(args: argparse.Namespace) -> int:
    """按数据集分组/文件/用例选择黄金用例，经本地 HTTP 执行并汇总确定性结果。"""
    try:
        files, group = select_dataset_files(args.group, args.file)
        cases = select_by_ids(load_golden(files), args.case)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


    user_id, room_id = _resolve_eval_ids(None, None)
    if args.backend == "java" and (not user_id or not room_id):
        print("ERROR: java backend requires EVAL_USER_ID and EVAL_ROOM_ID", file=sys.stderr)
        return 2
    user_id = user_id or "eval-user"
    room_id = room_id or "eval-room"

    if not cases:
        print("ERROR: no cases selected", file=sys.stderr)
        return 2
    try:
        await ensure_app_available()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    run_id = f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    reports = RunReports(run_id, len(cases), {
        "backend": args.backend, "group": group, "base_url": DEFAULT_BASE_URL,
    })
    print(f"backend={args.backend} group={group} files={len(files)} cases={len(cases)}")
    print(f"service={DEFAULT_BASE_URL} reports -> {reports.directory}")
    try:
        for case in cases:
            if case.skip_reason:
                report = {"case_id": case.id, "category": case.category, "status": "SKIP",
                          "passed": False, "failure": {"error": case.skip_reason}, "turns": []}
            else:
                suite = "intent" if file_group(Path(case.source_path)) == "intent" else "business"
                report = await run_case(
                    case, suite=suite, base_url=DEFAULT_BASE_URL, user_id=user_id, room_id=room_id,
                )
            reports.append(report)
            print(f"[{report['status']}] {case.id} ({case.category})")
    finally:
        summary = reports.finish()
        flush()
    return 0 if summary["passed"] == len(cases) else 1


async def _run_nodes(args: argparse.Namespace) -> int:
    """执行节点级 fixture；写副作用节点会在 runner 内被拒绝。"""
    try:
        fixtures = load_node_fixtures([Path(value) for value in args.data])
    except NodeRunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not fixtures:
        print("ERROR: no node fixtures selected", file=sys.stderr)
        return 2
    if args.transport == "http" and args.mock:
        print("ERROR: HTTP 节点回放不支持 --mock", file=sys.stderr)
        return 2

    api_key = os.getenv("NODE_RUN_API_KEY", "")
    if args.transport == "http" and not api_key:
        print("ERROR: HTTP 节点回放需要 NODE_RUN_API_KEY", file=sys.stderr)
        return 2
    client = (
        httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout)
        if args.transport == "http"
        else None
    )

    reports: list[dict[str, Any]] = []
    failed = 0
    skipped = 0
    for fixture in fixtures:
        report: dict[str, Any]
        try:
            if client is not None:
                result = await run_node_fixture_http(
                    fixture,
                    registry=DEFAULT_NODE_REGISTRY,
                    client=client,
                    api_key=api_key,
                )
            else:
                result = await run_node_fixture(
                    fixture,
                    registry=DEFAULT_NODE_REGISTRY,
                    mock_external=args.mock,
                )
        except NodeFixtureSkipError as exc:
            report = {
                "fixture_id": str(fixture.get("id") or ""),
                "node_name": str(fixture.get("node_name") or ""),
                "passed": False,
                "skipped": True,
                "reason": str(exc),
            }
        except NodeRunnerError as exc:
            report = {
                "fixture_id": str(fixture.get("id") or ""),
                "node_name": str(fixture.get("node_name") or ""),
                "passed": False,
                "error": str(exc),
            }
        else:
            report = asdict(result)
        reports.append(report)
        status = "SKIP" if report.get("skipped") else "PASS" if report["passed"] else "FAIL"
        print(f"[{status}] {report['fixture_id']} ({report['node_name']})")
        if report.get("skipped"):
            skipped += 1
            print(f"  {report['reason']}")
        elif not report["passed"]:
            failed += 1
            if report.get("error"):
                print(f"  {report['error']}")
            for diff in report.get("diffs", []):
                print(f"  {diff['path']}: expected={diff['expected']!r} actual={diff['actual']!r}")

    if client is not None:
        await client.aclose()

    summary = {
        "total": len(reports),
        "passed": len(reports) - failed - skipped,
        "failed": failed,
    }
    if skipped:
        summary["skipped"] = skipped
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"summary": summary, "reports": reports}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"report -> {output}")
    if failed:
        return 1
    return 0 if summary["passed"] else 2


def build_parser() -> argparse.ArgumentParser:
    """声明 CLI 参数及互斥执行模式。"""
    parser = argparse.ArgumentParser(prog="harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument(
        "--group", choices=("biz", "intent", "all"), default=None,
        help="数据集分组：biz / intent / all；缺省 biz，指定 --file 时按目录判定",
    )
    run.add_argument(
        "--file", action="append", type=Path,
        help="指定现役数据文件（biz 或 intent 目录下），可重复",
    )
    run.add_argument("--case", action="append", help="指定用例 ID，可重复；任一未命中即报错")
    run.add_argument(
        "--backend", choices=("mock", "java"), default="mock",
        help="评测后端声明：mock 或 java；已有 app 必须配置对应后端",
    )
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--base-url", default="http://127.0.0.1:8000")
    doctor.add_argument("--checkpoint", choices=("none", "mysql"), default="none")
    doctor.set_defaults(check_backend=True)
    node_run = subparsers.add_parser("node-run")
    node_run.add_argument("--data", action="append", required=True)
    node_run.add_argument("--out")
    node_run.add_argument(
        "--transport",
        choices=("direct", "http"),
        default="direct",
        help="direct 在当前进程调用节点；http 调受保护的外部节点执行接口",
    )
    node_run.add_argument("--base-url", default="http://127.0.0.1:8000")
    node_run.add_argument("--timeout", type=float, default=60.0)
    node_run.add_argument(
        "--mock",
        action="store_true",
        help="使用 fixture 中声明的 mock 数据替代节点外部依赖",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析命令行并以实际执行结果设置退出码。"""
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return asyncio.run(_doctor(args.base_url, args.checkpoint))
    if args.command == "node-run":
        return asyncio.run(_run_nodes(args))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
