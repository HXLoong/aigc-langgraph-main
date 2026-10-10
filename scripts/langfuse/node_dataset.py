"""节点 Dataset 发布、快照导出和 HTTP Experiment；业务基线不自动覆盖。"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from langfuse.experiment import Evaluation

from harness.langfuse_client import experiment_item_trace, flush, get_client, select_dataset_items
from harness.node_experiment import dataset_record, item_fixture, run_node_case
from harness.node_runner import load_node_fixtures
from harness.version import execution_metadata


def version_time(value: str | None) -> datetime:
    """固定本次读取版本；未指定时也记录取数时间，便于复现。"""
    version = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(UTC)
    if version.tzinfo is None:
        raise ValueError("数据集版本需要带时区的 ISO 时间")
    return version


def node_scores(*, output: dict[str, Any], **kwargs: Any) -> list[Evaluation]:
    """SKIP 不伪装为通过分数；执行的节点只按代码断言评分。"""
    if output.get("status") == "SKIP":
        return []
    return [Evaluation(name="det_node_pass", value=float(bool(output.get("passed"))),
                       comment="节点字段断言；差异见实验输出")]


async def run(args: argparse.Namespace) -> int:
    """按显式子命令发布或回归，平台和本地使用相同的字段比较器。"""
    client = get_client()
    if client is None:
        raise ValueError("此命令需要启用 Langfuse 并配置当前项目凭据")
    # 1. 所有样本先整体校验，再发布；不先上传一半再发现空断言。
    if args.command == "publish":
        records = [dataset_record(row, reviewer=args.reviewer, dataset_name=args.dataset)
                   for row in load_node_fixtures([args.input])]
        if not records:
            raise ValueError("没有可发布的节点样本")
        await asyncio.to_thread(client.create_dataset, name=args.dataset,
                                metadata={"suite": "node", "assertion_version": "node-fields-v1"})
        for record in records:
            await asyncio.to_thread(client.create_dataset_item, dataset_name=args.dataset, **record)
        print(f"已发布 {len(records)} 条节点标注：{args.dataset}")
        return 0

    # 2. 固定平台版本；导出仅保存到指定快照，不自动写回业务 fixture。
    version = version_time(args.version)
    dataset = await asyncio.to_thread(client.get_dataset, args.dataset, version=version)
    items = select_dataset_items(list(dataset.items), None)
    if args.command == "export":
        snapshot = {"dataset": args.dataset, "version": version.isoformat(),
            "review_status": "pending", "items": [{
                "id": item.id, "input": item.input, "expected_output": item.expected_output,
                "metadata": item.metadata, "source_trace_id": getattr(item, "source_trace_id", None),
                "source_observation_id": getattr(item, "source_observation_id", None),
            } for item in items]}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        print(f"已导出 {len(items)} 条；复核后再纳入对应基线：{args.out}")
        return 0

    # 3. 每个 Experiment item 内经 HTTP 执行，写节点即使被误标记也不会回放。
    reports: list[dict[str, Any]] = []
    run_name = f"node-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
    metadata = {**execution_metadata(), "dataset": args.dataset, "dataset_version": version.isoformat(),
                "execution_mode": "node_http", "assertion_version": "node-fields-v1"}

    async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        """坏样本计失败，不能从实验分母消失。"""
        try:
            async with httpx.AsyncClient(base_url=args.base_url, timeout=90) as http:
                with experiment_item_trace():
                    report = await run_node_case(item_fixture(item), client=http)
        except Exception as exc:
            report = {"status": "FAIL", "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        report["dataset_item_id"] = item.id
        reports.append(report)
        return report

    if items:
        await asyncio.to_thread(client.run_experiment, name=run_name, run_name=run_name,
            data=items, task=task, evaluators=[node_scores], max_concurrency=args.concurrency,
            metadata=metadata)
        flush()
    completed = {row["dataset_item_id"] for row in reports}
    reports.extend({"dataset_item_id": item.id, "status": "FAIL", "passed": False,
                    "error": "Experiment 未执行该样本"} for item in items if item.id not in completed)
    summary = {**metadata, "run_name": run_name, "total": len(items),
        "passed": sum(row["status"] == "PASS" for row in reports),
        "failed": sum(row["status"] == "FAIL" for row in reports),
        "skipped": sum(row["status"] == "SKIP" for row in reports), "cases": reports}
    summary["acceptance"] = "pending" if not summary["passed"] and not summary["failed"] else "executed"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"节点回归 PASS {summary['passed']}, FAIL {summary['failed']}, SKIP {summary['skipped']}")
    return 1 if summary["failed"] else 2 if summary["acceptance"] == "pending" else 0


def main() -> int:
    """命令行明确区分发布写操作、只读导出和安全节点回归。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--dataset", required=True)
    publish.add_argument("--input", required=True, type=Path)
    publish.add_argument("--reviewer", required=True)
    for name in ("export", "run"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", required=True)
        command.add_argument("--version")
        command.add_argument("--out", required=True, type=Path)
        if name == "run":
            command.add_argument("--base-url", default="http://127.0.0.1:8201")
            command.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if getattr(args, "concurrency", 1) < 1:
        parser.error("concurrency 必须为正数")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
