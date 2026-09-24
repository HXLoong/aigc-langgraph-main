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

import httpx

from harness.differ import (
    FieldDiff,
    check_case_assertions,
    check_structured_assertions,
    check_text_assertions,
)
from harness.golden import (
    GoldenCase,
    filter_by_category,
    filter_by_ids,
    load_golden,
    select_runnable,
)
from harness.multi_turn import MultiTurnResult, run_case_multi
from harness.node_registry import DEFAULT_NODE_REGISTRY
from harness.node_runner import (
    NodeFixtureSkipError,
    NodeRunnerError,
    load_node_fixtures,
    run_node_fixture,
    run_node_fixture_http,
)


def _paths(values: list[str] | None) -> list[Path] | Path | None:
    if not values:
        return None
    paths = [Path(value) for value in values]
    return paths[0] if len(paths) == 1 else paths


def _turn_diffs(
    case: GoldenCase, result: MultiTurnResult, backend: str = "real"
) -> dict[int | str, list[FieldDiff]]:
    diffs: dict[int | str, list[FieldDiff]] = {}
    for outcome, spec in zip(result.turns, case.turns, strict=False):
        turn_diffs = check_text_assertions(
            outcome.reply_text, spec, allow_dry_run=backend == "dry-run"
        )
        turn_diffs.extend(check_structured_assertions(
            outcome.outputs, spec.expected, quote_content=outcome.quote_content,
        ))
        diffs[outcome.index] = turn_diffs
    if case.expected_scope == "any_turn":
        case_diffs = check_case_assertions(
            [outcome.outputs for outcome in result.turns], case.expected,
            quote_contents=[outcome.quote_content for outcome in result.turns],
        )
        if case_diffs:
            diffs["case"] = case_diffs
    if result.failure:
        # 早停后未执行的轮次逐轮显式记失败（ADR 0024 D6），多轮 case 不得因早停静默通过
        stop_turn, kind = result.failure.get("turn"), result.failure.get("kind")
        for index in range(len(result.turns) + 1, len(case.turns) + 1):
            diffs[index] = [
                FieldDiff(
                    path="runtime",
                    expected="turn executed",
                    actual=f"not executed: early stop at turn {stop_turn} ({kind})",
                )
            ]
    return diffs


def _case_status(result: MultiTurnResult, diffs: dict[int | str, list[FieldDiff]]) -> str:
    """PASS / FAIL / REJECTED：业务拒绝不算 PASS，单独成桶（ADR 0024 D6）。"""
    if any(diffs.values()):
        return "FAIL"
    if result.failure is None:
        return "PASS"
    return "REJECTED" if result.failure.get("kind") == "business_reject" else "FAIL"


def _report_case(
    case: GoldenCase, result: MultiTurnResult, diffs: dict[int | str, list[FieldDiff]]
) -> dict[str, Any]:
    status = _case_status(result, diffs)
    return {
        "case_id": case.id,
        "category": case.category,
        "dialect": case.dialect,
        "case_diff": [item.model_dump() for item in diffs.get("case", [])],
        "source_path": case.source_path,
        "source_line": case.source_line,
        "conversation_id": result.conversation_id,
        "status": status,
        "passed": status == "PASS",
        "failure": result.failure,
        "turns": [
            {
                "turn": outcome.index,
                "scene": outcome.scene,
                "raw": outcome.send_text,
                "reply": outcome.reply_text,
                "quote_passed": outcome.quote_passed,
                "product_type": outcome.product_type,
                "intent": outcome.intent,
                "tickers": outcome.tickers,
                "place_params": outcome.place_params,
                "api_code": outcome.api_code,
                "api_result": outcome.api_result,
                "error": outcome.error,
                "trace": outcome.trace,
                "elapsed_ms": outcome.elapsed_ms,
                "diff": [item.model_dump() for item in diffs.get(outcome.index, [])],
            }
            for outcome in result.turns
        ],
    }


def _summarize(reports: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        status: sum(1 for r in reports if r["status"] == status)
        for status in ("PASS", "FAIL", "REJECTED")
    }
    return {
        "total": len(reports),
        "passed": counts["PASS"],
        "failed": counts["FAIL"],
        "rejected": counts["REJECTED"],
        "pass_rate": counts["PASS"] / len(reports) if reports else 0.0,
    }


def _render_markdown(reports: list[dict[str, Any]]) -> str:
    summary = _summarize(reports)
    lines = [
        "# Harness Regression Report",
        "",
        f"- PASS: {summary['passed']}",
        f"- FAIL: {summary['failed']}",
        f"- REJECTED: {summary['rejected']}  (backend business reject; not counted as PASS)",
        f"- TOTAL: {summary['total']}",
        "",
        "| case | category | status | failure |",
        "|---|---|---|---|",
    ]
    for report in reports:
        status = report["status"]
        lines.append(
            f"| `{report['case_id']}` | `{report['category']}` | {status} | "
            f"{report.get('failure') or ''} |"
        )
    return "\n".join(lines) + "\n"


#: --backend 取值 → 服务端 /health.backend_mode 必须是什么（mock 只是把真后端 URL 指向 mock_api）
_REQUIRED_SERVER_MODE = {"real": "real", "mock": "real", "dry-run": "dry-run"}


def _backend_gate(backend: str | None, server_mode: str | None) -> str | None:
    """返回阻断原因；None 表示放行。旧服务端不报模式时只对 dry-run 严格（不能假定写类已被拦截）。"""
    if backend is None:
        return None
    wanted = _REQUIRED_SERVER_MODE[backend]
    if server_mode is None:
        return (
            "--backend dry-run requires the server to report backend_mode=dry-run in /health; got none"
            if backend == "dry-run"
            else None
        )
    if server_mode != wanted:
        return f"--backend {backend} needs server backend_mode={wanted}, but /health reports {server_mode!r}"
    return None


async def _doctor(base_url: str, checkpoint: str = "none", backend: str | None = None) -> int:
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


def _dotenv_values() -> dict[str, str]:
    """读 repo 根 .env 的 KEY=VALUE（忽略注释 / 空行）。"""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve_eval_ids(user_id: str | None, room_id: str | None) -> tuple[str, str]:
    """显式传参优先；缺省回读 repo 根 .env 的 EVAL_USER_ID / EVAL_ROOM_ID。"""
    if user_id and room_id:
        return user_id, room_id
    values = _dotenv_values()
    return user_id or values.get("EVAL_USER_ID", ""), room_id or values.get("EVAL_ROOM_ID", "")


async def _run(args: argparse.Namespace) -> int:
    gate = await _doctor(args.base_url, args.checkpoint, backend=args.backend)
    if args.check_backend or gate != 0:
        return gate
    user_id, room_id = _resolve_eval_ids(args.user_id, args.room_id)
    if not user_id or not room_id:
        print(
            "ERROR: --user-id and --room-id are required (or EVAL_USER_ID / EVAL_ROOM_ID in .env)",
            file=sys.stderr,
        )
        return 2
    cases = filter_by_ids(
        filter_by_category(
            load_golden(_paths(args.data), include_unified=args.include_unified), args.category,
        ), args.case,
    )
    cases, skipped = select_runnable(cases)
    if skipped:
        print(
            f"skipped {len(skipped)} unrunnable cases (skip_reason set), e.g. {skipped[0].id}: {skipped[0].skip_reason}"
        )
    if args.limit is not None:
        cases = cases[: args.limit]
    if not cases:
        print("ERROR: no cases selected", file=sys.stderr)
        return 2

    print(f"base_url={args.base_url} backend={args.backend} checkpoint={args.checkpoint}")
    print(f"running {len(cases)} cases; write-side effects are enabled by server configuration")
    reports: list[dict[str, Any]] = []
    for case in cases:
        result = await run_case_multi(
            case,
            base_url=args.base_url,
            user_id=user_id,
            room_id=room_id,
            turn_interval=args.turn_interval,
        )
        diffs = _turn_diffs(case, result, backend=args.backend)
        report = _report_case(case, result, diffs)
        reports.append(report)
        print(f"[{report['status']}] {case.id} ({case.category})")
        if args.stop_on_fail and not report["passed"]:
            break

    out_dir = Path(args.out or ".harness-runs") / f"probe-{time.strftime('%Y%m%d-%H%M%S')}"
    failures = out_dir / "failures"
    failures.mkdir(parents=True, exist_ok=True)
    for report in reports:
        if not report["passed"]:
            (failures / f"{report['case_id']}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    summary = {
        **_summarize(reports),
        "backend": args.backend,
        "checkpoint": args.checkpoint,
        "base_url": args.base_url,
        "reports": reports,
    }
    passed = summary["passed"]
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(_render_markdown(reports), encoding="utf-8")
    print(f"reports -> {out_dir}")
    return 0 if passed == len(reports) else 1


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
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--data", action="append")
    run.add_argument(
        "--include-unified", action="store_true",
        help="显式追加 tests/fixtures/unified_golden.jsonl 历史参考集（默认只读 biz）",
    )
    run.add_argument("--base-url", default="http://127.0.0.1:8000")
    run.add_argument("--backend", choices=("real", "mock", "dry-run"), default="real")
    run.add_argument("--checkpoint", choices=("none", "mysql"), default="none")
    run.add_argument("--check-backend", action="store_true")
    run.add_argument("--turn-interval", type=float, default=0.0)
    run.add_argument("--stop-on-fail", action="store_true")
    run.add_argument("--limit", type=int)
    run.add_argument("--case", action="append")
    run.add_argument("--category")
    run.add_argument("--out")
    run.add_argument("--user-id", default=os.getenv("EVAL_USER_ID", ""))
    run.add_argument("--room-id", default=os.getenv("EVAL_ROOM_ID", ""))
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
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return asyncio.run(_doctor(args.base_url, args.checkpoint))
    if args.command == "node-run":
        return asyncio.run(_run_nodes(args))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
