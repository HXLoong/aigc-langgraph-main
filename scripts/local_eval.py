"""Local Java message fixtures + the production HTTP harness; never targets a remote app."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiomysql
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.llm import clients as llm_clients
from app.prompts import load_prompt
from app.storage.mysql import connection_args
from app.tools.ticker_client import TickerClientHttpx
from harness.cli import _doctor, _render_markdown, _report_case, _summarize, _turn_diffs
from harness.golden import GoldenCase, filter_by_ids, load_golden
from harness.multi_turn import MultiTurnResult, run_case_multi

logger = logging.getLogger(__name__)


class CapabilityProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(description="结构化输出检查结果，固定为 ready")


async def probe_text_models() -> list[dict[str, Any]]:
    checked: set[tuple[str, str]] = set()
    results: list[dict[str, Any]] = []
    prompt = load_prompt("system", "capability_probe")
    for factory in (llm_clients.get_qwen_standard, llm_clients.get_qwen_thinking, llm_clients.get_qwen_complex):
        model = factory()
        key = (str(model.openai_api_base), model.model_name)
        if key not in checked:
            try:
                output = await model.with_structured_output(CapabilityProbe).ainvoke([("system", prompt.system)])
                if CapabilityProbe.model_validate(output).status != "ready":
                    raise ValueError("unexpected capability response")
            except Exception as exc:
                raise ValueError(f"structured output unavailable: {model.model_name}") from exc
            checked.add(key)
        results.append({"factory": factory.__name__, "model": model.model_name, "structured_output": True})
    return results


def require_local(url: str) -> None:
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("local application/database target required")


def latency_percentiles(values: list[int]) -> dict[str, int | None]:
    """Empirical nearest-rank percentiles, including the tail for small samples."""
    ordered = sorted(values)
    return {
        label: ordered[max(0, math.ceil(len(ordered) * percentile) - 1)] if ordered else None
        for label, percentile in (("p50_ms", .5), ("p95_ms", .95), ("p99_ms", .99))
    }


class LocalJavaMessages:
    def __init__(self, pool: aiomysql.Pool, run_id: str) -> None:
        self.pool = pool
        self.run_id = run_id
        self.message_ids: list[int] = []
        self.counterparties: dict[tuple[str, str, str], str] = {}

    async def prepare(self, inputs: dict[str, Any]) -> None:
        settings = get_settings()
        async with self.pool.acquire() as connection, connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO xbot_chat_room_message "
                "(id, room_id, conversation_id, sender_id, guid, content, raw_content, quote_content, "
                "at_bot, msg_type, by_bot, status, bot_name, creator, receive_time) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,6,%s,%s,NOW())",
                (inputs["message_id"], inputs["room_id"], inputs["conversation_id"], inputs["user_id"],
                 settings.eval_guid, inputs["message_content"], inputs["raw_text"], inputs["quote_content"],
                 int(bool(inputs["at_bot"])), "langgraph-local-eval", self.run_id),
            )
        self.message_ids.append(inputs["message_id"])
        inputs["guid"] = settings.eval_guid
        for product, key in (("OPTION", "option_counterparties"), ("TRS", "swap_counterparties")):
            cache_key = (inputs["room_id"], inputs["user_id"], product)
            if cache_key not in self.counterparties:
                rows = await TickerClientHttpx().list_counterparty(
                    inputs["room_id"], user_id=inputs["user_id"], business_type=product,
                    message_id=inputs["message_id"],
                )
                self.counterparties[cache_key] = json.dumps(rows, ensure_ascii=False)
            inputs[key] = self.counterparties[cache_key]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    for url in (args.base_url, settings.otc_api_base_url, settings.mysql_uri):
        require_local(url)
    database_args = connection_args(settings.mysql_uri)
    if not settings.eval_user_id or not settings.eval_room_id:
        raise ValueError("EVAL_USER_ID and EVAL_ROOM_ID are required")
    backend = "dry-run" if getattr(settings, "dry_run_backend", False) else "real"
    gate = await _doctor(args.base_url, checkpoint="mysql", backend=backend)
    if gate:
        return gate
    models = await probe_text_models()
    cases = filter_by_ids(load_golden(Path(args.data)), args.case)
    if args.limit:
        cases = cases[:args.limit]
    if not cases or any(case.skip_reason for case in cases):
        raise ValueError("selected cases must be nonempty and all executable")
    run_id = f"local-{time.strftime('%Y%m%d-%H%M%S')}"
    directory = Path(args.out or ".harness-runs") / run_id
    directory.mkdir(parents=True, exist_ok=False)
    pool = await aiomysql.create_pool(
        **database_args, autocommit=True, minsize=1, maxsize=args.concurrency,
    )
    fixtures = LocalJavaMessages(pool, run_id)
    semaphore = asyncio.Semaphore(args.concurrency)
    reports: list[dict[str, Any]] = []
    latencies: list[int] = []
    manifest = {
        "run": run_id, "base_url": args.base_url, "backend": backend, "checkpoint": "mysql",
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "cases": len(cases), "turns": sum(len(case.turns) for case in cases),
        "model": settings.qwen_model_standard,
        "models": models,
        "fixtures": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(args.data).glob("*.jsonl")},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    logger.info("local evaluation started: %s cases=%s", directory, len(cases))

    async def execute(case: GoldenCase) -> None:
        async with semaphore:
            try:
                result = await run_case_multi(
                    case, base_url=args.base_url, user_id=settings.eval_user_id,
                    room_id=settings.eval_room_id, before_turn=fixtures.prepare,
                    timeout=args.timeout, turn_interval=args.turn_interval,
                )
            except Exception as exc:  # preparation failure must be reported, not dropped
                result = MultiTurnResult(case_id=case.id, conversation_id="", remaining_turns=len(case.turns),
                    failure={"kind": "preparation_error", "error": type(exc).__name__})
                logger.error("case=%s preparation=%s", case.id, type(exc).__name__)
            report = _report_case(case, result, _turn_diffs(case, result))
            reports.append(report)
            latencies.extend(turn.elapsed_ms for turn in result.turns)
            with (directory / "cases.jsonl").open("a") as stream:
                stream.write(json.dumps(report, ensure_ascii=False) + "\n")
            logger.info("[%s/%s] %s %s", len(reports), len(cases), report["status"], case.id)

    try:
        await asyncio.gather(*(execute(case) for case in cases))
    finally:
        (directory / "message_ids.json").write_text(json.dumps(fixtures.message_ids))
        pool.close()
        await pool.wait_closed()
    reports.sort(key=lambda report: report["case_id"])
    percentiles = latency_percentiles(latencies)
    summary = {**manifest, **_summarize(reports), **percentiles, "reports": reports}
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (directory / "report.md").write_text(_render_markdown(reports))
    logger.info("local evaluation complete: %s", {key: value for key, value in summary.items() if key not in {"reports", "fixtures"}})
    return 0 if summary["passed"] == len(cases) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8201")
    parser.add_argument("--data", default="tests/fixtures/categories")
    parser.add_argument("--case", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--turn-interval", type=float, default=1.0)
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("concurrency must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
