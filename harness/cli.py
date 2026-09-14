"""Command line entry point for categories-based HTTP regression."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from harness.differ import FieldDiff, check_structured_assertions, check_text_assertions
from harness.golden import GoldenCase, filter_by_category, filter_by_ids, load_golden
from harness.multi_turn import MultiTurnResult, run_case_multi


def _paths(values: list[str] | None) -> list[Path] | Path | None:
    if not values:
        return None
    paths = [Path(value) for value in values]
    return paths[0] if len(paths) == 1 else paths


def _turn_diffs(case: GoldenCase, result: MultiTurnResult) -> dict[int, list[FieldDiff]]:
    diffs: dict[int, list[FieldDiff]] = {}
    for outcome, spec in zip(result.turns, case.turns, strict=False):
        turn_diffs = check_text_assertions(outcome.reply_text, spec)
        turn_diffs.extend(check_structured_assertions(outcome.outputs, spec.expected))
        diffs[outcome.index] = turn_diffs
    if result.failure and not result.turns:
        diffs[result.failure["turn"]] = [
            FieldDiff(path="runtime", expected="successful HTTP response", actual=result.failure)
        ]
    return diffs


def _report_case(case: GoldenCase, result: MultiTurnResult, diffs: dict[int, list[FieldDiff]]) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "category": case.category,
        "source_path": case.source_path,
        "source_line": case.source_line,
        "conversation_id": result.conversation_id,
        "passed": not any(diffs.values()) and (
            not result.failure or result.failure.get("kind") == "business_reject"
        ),
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
                "diff": [item.model_dump() for item in diffs.get(outcome.index, [])],
            }
            for outcome in result.turns
        ],
    }


def _render_markdown(reports: list[dict[str, Any]]) -> str:
    passed = sum(1 for report in reports if report["passed"])
    lines = [
        "# Harness Regression Report",
        "",
        f"- PASS: {passed}",
        f"- FAIL: {len(reports) - passed}",
        f"- TOTAL: {len(reports)}",
        "",
        "| case | category | status | failure |",
        "|---|---|---|---|",
    ]
    for report in reports:
        status = "PASS" if report["passed"] else "FAIL"
        lines.append(
            f"| `{report['case_id']}` | `{report['category']}` | {status} | "
            f"{report.get('failure') or ''} |"
        )
    return "\n".join(lines) + "\n"


async def _doctor(base_url: str, checkpoint: str = "none") -> int:
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
    gate = await _doctor(args.base_url, args.checkpoint)
    if args.check_backend or gate != 0:
        return gate
    if args.backend == "dry-run":
        print("WARNING: dry-run must be configured in the already running uvicorn process")
    user_id, room_id = _resolve_eval_ids(args.user_id, args.room_id)
    if not user_id or not room_id:
        print(
            "ERROR: --user-id and --room-id are required (or EVAL_USER_ID / EVAL_ROOM_ID in .env)",
            file=sys.stderr,
        )
        return 2
    cases = filter_by_ids(
        filter_by_category(load_golden(_paths(args.data)), args.category), args.case
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
        diffs = _turn_diffs(case, result)
        report = _report_case(case, result, diffs)
        reports.append(report)
        print(f"[{'PASS' if report['passed'] else 'FAIL'}] {case.id} ({case.category})")
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
    passed = sum(1 for report in reports if report["passed"])
    summary = {
        "total": len(reports),
        "passed": passed,
        "failed": len(reports) - passed,
        "pass_rate": passed / len(reports) if reports else 0.0,
        "backend": args.backend,
        "checkpoint": args.checkpoint,
        "base_url": args.base_url,
        "reports": reports,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(_render_markdown(reports), encoding="utf-8")
    print(f"reports -> {out_dir}")
    return 0 if passed == len(reports) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--data", action="append")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return asyncio.run(_doctor(args.base_url, args.checkpoint))
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
