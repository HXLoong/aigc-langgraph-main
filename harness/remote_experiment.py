"""Langfuse webhook 内部适配；复用黄金集 HTTP 执行与本地评分。"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from langfuse.experiment import Evaluation

from app.config import get_settings
from harness.golden import DATASETS_ROOT, GoldenCase, dataset_expected, dataset_input, load_golden
from harness.http_evaluation import DEFAULT_BASE_URL, ensure_app_available, run_case
from harness.langfuse_client import experiment_item_trace, flush, get_client
from harness.run_reports import RunReports


def local_dataset(dataset_name: str) -> Path:
    """平台名称只映射现役黄金文件，拒绝任意文件路径。"""
    parts = dataset_name.split("/")
    if len(parts) < 2 or parts[0] not in {"biz", "intent"} or any(
        not part or part in {".", ".."} or "\\" in part or ":" in part for part in parts
    ):
        raise ValueError("datasetName 必须对应 biz/ 或 intent/ 下的黄金文件")
    path = DATASETS_ROOT.joinpath(*parts[:-1], f"{parts[-1]}.jsonl").resolve()
    if DATASETS_ROOT.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"黄金数据文件不存在：{dataset_name}")
    return path


def bind_items(items: list[Any], cases: list[GoldenCase], ids: list[str] | None,
               limit: int | None) -> list[tuple[Any, GoldenCase]]:
    """平台条目与 git 输入、期望一致才执行，选择不得静默漏项。"""
    by_case = {case.id: case for case in cases}
    wanted = set(ids or [])
    matched: set[str] = set()
    selected: list[tuple[Any, GoldenCase]] = []
    seen: set[str] = set()
    for item in items:
        status = getattr(item, "status", "ACTIVE")
        if str(getattr(status, "value", status)).upper() == "ARCHIVED":
            continue
        metadata = item.metadata or {}
        candidates = [str(metadata.get(key) or "") for key in ("id", "case_id", "caseNo")]
        case_id = next((value for value in candidates if value in by_case), "")
        aliases = {str(item.id), *candidates}
        if wanted and not wanted.intersection(aliases):
            continue
        matched.update(wanted.intersection(aliases))
        if not case_id:
            raise ValueError(f"平台条目 {item.id} 没有对应的 git 黄金用例")
        if case_id in seen:
            raise ValueError(f"平台用例重复：{case_id}")
        case = by_case[case_id]
        if item.input != dataset_input(case) or item.expected_output != dataset_expected(case):
            raise ValueError(f"平台用例与 git 不一致：{case_id}；请先同步黄金数据集")
        selected.append((item, case))
        seen.add(case_id)
    if wanted - matched:
        raise ValueError(f"未找到用例 ID：{', '.join(sorted(wanted - matched))}")
    if not wanted and seen != set(by_case):
        raise ValueError("平台数据集未完整同步 git 黄金用例")
    return selected[:limit] if limit else selected


def local_scores(*, output: dict[str, Any], **kwargs: Any) -> list[Evaluation]:
    """将已有本地结论上传，不重新评分或等待平台 Rule。"""
    if output["status"] == "SKIP":
        return []
    name = "det_intent_pass" if output.get("suite") == "intent" else "det_business_pass"
    scores = [Evaluation(name=name, value=float(bool(output["passed"])),
                         comment="本地确定性结论；差异见实验输出")]
    for score in output.get("intent_scores", []):
        if score["metadata"]["assertion_count"]:
            scores.append(Evaluation(name=score["name"], value=score["value"],
                                     comment=score["comment"]))
    return scores


async def run(args: argparse.Namespace) -> int:
    """平台只触发实验，业务请求仍发送到已有 8000 服务。"""
    path = local_dataset(args.dataset)
    suite = "intent" if args.dataset.startswith("intent/") else "business"
    if suite == "business" and args.concurrency != 1:
        raise ValueError("业务实验 concurrency 必须为 1")
    settings = get_settings()
    if not settings.eval_user_id or not settings.eval_room_id:
        raise ValueError("平台实验需要 EVAL_USER_ID 和 EVAL_ROOM_ID 授权测试身份")
    client = get_client()
    if client is None:
        raise ValueError("平台实验需要 ENABLE_LANGFUSE=true 和有效项目凭据")
    dataset = await asyncio.to_thread(client.get_dataset, args.dataset)
    pairs = bind_items(list(dataset.items), load_golden([path]), args.ids, args.limit)
    if not pairs:
        raise ValueError("没有可执行的黄金用例")
    await ensure_app_available()
    run_name = f"experiment-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    reports = RunReports(run_name, len(pairs), {
        "dataset": args.dataset, "base_url": DEFAULT_BASE_URL, "suite": suite,
    })
    by_item = {str(item.id): case for item, case in pairs}
    print(f"service={DEFAULT_BASE_URL} reports -> {reports.directory}")

    async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        case = by_item[str(item.id)]
        try:
            if case.skip_reason:
                report = {"case_id": case.id, "category": case.category, "status": "SKIP",
                          "passed": False, "failure": {"error": case.skip_reason}, "turns": []}
            else:
                with experiment_item_trace():
                    report = await run_case(case, suite=suite, base_url=DEFAULT_BASE_URL,
                                            user_id=settings.eval_user_id,
                                            room_id=settings.eval_room_id)
        except Exception as exc:
            report = {"case_id": case.id, "category": case.category, "status": "FAIL",
                      "passed": False, "failure": {"error": f"{type(exc).__name__}: {exc}"},
                      "input": dataset_input(case), "expected_output": dataset_expected(case),
                      "turns": []}
        report.update(dataset_item_id=str(item.id), suite=suite)
        reports.append(report)
        return report

    try:
        await asyncio.to_thread(client.run_experiment, name=run_name, run_name=run_name,
                                data=[item for item, _ in pairs], task=task,
                                evaluators=[local_scores], max_concurrency=args.concurrency,
                                metadata={"dataset": args.dataset, "suite": suite})
    finally:
        summary = reports.finish()
        flush()
    return 0 if summary["passed"] == len(pairs) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    if args.concurrency < 1 or (args.limit is not None and args.limit < 1):
        parser.error("limit 和 concurrency 必须是正整数")
    try:
        return asyncio.run(run(args))
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
