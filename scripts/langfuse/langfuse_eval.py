"""经 HTTP 执行数据集，使用确定性断言，并关联 Langfuse Experiment。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import get_settings
from harness.evaluation import summarize
from harness.golden import (
    GoldenCase,
    build_overview,
    dataset_expected,
    dataset_input,
    filter_by_category,
    filter_by_ids,
    load_golden,
    normalize_case,
)
from harness.http_evaluation import intent_evaluations, run_case
from harness.langfuse_client import experiment_item_trace, flush, get_client
from harness.reporting import render_markdown
from harness.version import execution_metadata

DATASET_NAME = "biz/option_inquiry"
SUITES = ("intent", "business")
DEFAULT_SUITE = "business"
ASSERTION_VERSION = "deterministic-v1"


def resolve_suite(suite: str | None, local_paths: list[Path] | None, dataset_name: str | None) -> str:
    """显式参数优先，其次按当前数据目录或 Dataset 名称判定套件。"""
    if suite is not None:
        if suite not in SUITES:
            raise ValueError("unknown evaluation suite")
        return suite
    if local_paths and all("intent" in path.parts for path in local_paths):
        return "intent"
    return "intent" if (dataset_name or "").startswith(("intent/", "intent_", "intent-")) else "business"


def judge_enabled(suite: str, *, no_judge: bool = False) -> bool:
    """兼容旧调用方的查询接口；所有套件都由代码评分。"""
    return False


class _LocalItem:
    """本地 fixture 的平台投影；输入与期望分别保存，不向执行器泄漏标签。"""

    def __init__(self, case: GoldenCase, suite: str = DEFAULT_SUITE) -> None:
        """复用唯一数据集投影，固定 case 身份及断言版本。"""
        self.case = case
        self.id = case.id
        self.input = dataset_input(case)
        self.expected_output = self.expected_structured = dataset_expected(case)
        self.metadata = {"id": case.id, "case_id": case.id, "category": case.category,
                         "suite": suite, "overview": build_overview(case)[:180], "assertion_version": ASSERTION_VERSION}
        self.has_instruments = any(turn.expected.get("instruments") for turn in case.turns)
        self.has_rejections = any(turn.expected.get("rejection") for turn in case.turns)

    def as_item(self) -> dict[str, Any]:
        """SDK 的本地 Experiment 输入使用公开的字典结构。"""
        return {"input": self.input, "expected_output": self.expected_output, "metadata": self.metadata}


def _item_value(item: Any, name: str, default: Any = None) -> Any:
    """兼容 SDK Dataset Item 与本地实验字典的同一字段。"""
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _case_id(item: Any) -> str:
    """所有执行、补缺和报告使用同一稳定身份，平台 UUID 只作最后兜底。"""
    metadata = _item_value(item, "metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return str(metadata.get("case_id") or metadata.get("id") or _item_value(item, "id", "unknown"))


def item_case(item: Any) -> GoldenCase:
    """把平台首轮及子轮输入、断言合并成同一个 GoldenCase。"""
    if isinstance(item, _LocalItem):
        return item.case
    inp = _item_value(item, "input") or {}
    expected = _item_value(item, "expected_output", _item_value(item, "expectedOutput", {})) or {}
    if not isinstance(inp, dict) or not isinstance(expected, dict):
        raise ValueError("Dataset input 与 expected_output 必须是结构化对象")
    metadata = _item_value(item, "metadata") or {}
    case_id = _case_id(item)
    input_turns = [inp, *(inp.get("sub_scenes") or [])]
    expected_turns = [expected, *(expected.get("sub_scenes") or [])]
    turns = []
    for index, turn in enumerate(input_turns):
        assertions = expected_turns[index] if index < len(expected_turns) else {}
        turns.append({**{k: v for k, v in turn.items() if k != "sub_scenes"},
                      **{k: v for k, v in assertions.items() if k != "sub_scenes"}})
    return normalize_case({"caseNo": case_id, "category": metadata.get("category", "dataset"),
                           **turns[0], "sub_scenes": turns[1:]}, origin=f"langfuse/{case_id}:1")


def select_dataset_items(items: list[Any], ids: list[str] | None) -> list[Any]:
    """只执行启用的 Dataset Item，可按平台 ID 或稳定 case ID 选择。"""
    wanted = set(ids or [])
    selected = []
    for item in items:
        status = _item_value(item, "status", "ACTIVE")
        if str(getattr(status, "value", status)).upper() == "ARCHIVED":
            continue
        metadata = _item_value(item, "metadata") or {}
        if not wanted or wanted.intersection({str(_item_value(item, "id", "")), str(metadata.get("id", "")), str(metadata.get("case_id", ""))}):
            selected.append(item)
    return selected


def code_evaluations(item: Any, output: dict[str, Any]) -> list[Any]:
    """将同源意图评分转换为 SDK Evaluation，不调用 Judge。"""
    from langfuse.experiment import Evaluation

    return [Evaluation(**score) for score in intent_evaluations(item_case(item), output)]


def deterministic_scores(*, output: dict[str, Any], **kwargs: Any) -> list[Any]:
    """Experiment 评分直接复用已完成的确定性差异结果。"""
    from langfuse.experiment import Evaluation

    scores = output.get("evaluations") if isinstance(output, dict) else None
    if not scores:
        return [Evaluation(name="det_execution_pass", value=0.0, comment="没有可评分的执行结果")]
    return [Evaluation(**score) for score in scores]


def case_passed(suite: str, evaluations: list[Any]) -> bool:
    """所有明确评分必须通过；空评分不可通过。"""
    return bool(evaluations) and all(float(item.value or 0) == 1 for item in evaluations)


def passes_quality_gate(summary: dict[str, Any], threshold: float) -> bool:
    """总通过率与分桶同时满足门槛，不用拒绝样本抬高正向通过率。"""
    if not summary.get("total") or summary["pass_rate"] < threshold:
        return False
    buckets = summary.get("acceptance_buckets", {})
    positive, rejection = buckets.get("executable", {}), buckets.get("expected_rejection", {})
    return not ((positive.get("total") and positive["pass_rate"] < threshold)
                or (rejection.get("total") and rejection["passed"] != rejection["total"]))


async def run_langgraph_pipeline(
    *, item: Any, suite: str = DEFAULT_SUITE, base_url: str = "http://127.0.0.1:8201",
    run_name: str = "eval", prepare_java: bool = False, **kwargs: Any,
) -> dict[str, Any]:
    """HTTP 是唯一业务执行入口；可显式准备本地 Java 测试消息。"""
    settings = get_settings()
    case = item_case(item)
    user_id = settings.eval_user_id or ("eval-user" if suite == "intent" else "")
    room_id = settings.eval_room_id or ("eval-room" if suite == "intent" else "")
    if not user_id or not room_id:
        raise ValueError("业务评测需要 EVAL_USER_ID 与 EVAL_ROOM_ID")
    pool = None
    before_turn = kwargs.get("before_turn")
    try:
        # SQL 准备发生在当前执行任务自己的 loop，不能跨 SDK 工作线程复用连接池。
        if prepare_java and suite == "business":
            import aiomysql

            from app.storage.mysql import connection_args
            from scripts.local_eval import LocalJavaMessages, require_local

            for url in (base_url, settings.otc_api_base_url, settings.mysql_uri):
                require_local(url)
            pool = await aiomysql.create_pool(**connection_args(settings.mysql_uri), autocommit=True, minsize=1, maxsize=1)
            before_turn = LocalJavaMessages(pool, run_name).prepare
        return await run_case(case, suite=suite, base_url=base_url, user_id=user_id, room_id=room_id,
            client=kwargs.get("client"), before_turn=before_turn, trace_metadata={"run_name": run_name, "suite": suite})
    finally:
        if pool is not None:
            pool.close()
            await pool.wait_closed()


def _metadata() -> dict[str, str]:
    """复用所有评测入口一致的实际代码与模型指纹。"""
    return execution_metadata()


def _failed_report(case_id: str, reason: str, *, item: Any = None) -> dict[str, Any]:
    """基础设施异常也保留一个失败条目，不能从统计分母消失。"""
    return {"case_id": case_id, "id": case_id, "status": "FAIL", "passed": False,
            "input": _item_value(item, "input", {}),
            "expected_output": _item_value(item, "expected_output", {}),
            "turns": [], "failure": {"kind": "execution_error", "error": reason},
            "evaluations": [{"name": "det_execution_pass", "value": 0.0, "comment": reason}]}


async def _run_items(
    items: list[Any], *, suite: str, concurrency: int, base_url: str,
    prepare_java: bool, report: Path | None, metadata_extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """等待全部执行与评分完成再统计，SDK 丢失的失败条目显式补回。"""
    if not items:
        raise ValueError("没有选中的可执行数据集条目")
    started = time.monotonic()
    run_name = f"{suite}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    metadata = {**_metadata(), **(metadata_extra or {})}
    metadata["dataset_hash"] = hashlib.sha256(json.dumps([
        {"input": _item_value(item, "input"), "expected": _item_value(item, "expected_output")}
        for item in items
    ], ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    reports: list[dict[str, Any]] = []

    async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        """捕获单个用例故障，其余用例继续且该条仍计失败。"""
        case_id = _case_id(item)
        try:
            with experiment_item_trace(active=client is not None):
                output = await run_langgraph_pipeline(item=item, suite=suite, base_url=base_url,
                                                      run_name=run_name, prepare_java=prepare_java)
        except Exception as exc:
            output = _failed_report(case_id, f"{type(exc).__name__}: {exc}", item=item)
        reports.append(output)
        return output

    client = get_client()
    if client is not None:
        # SDK 公共接口在自己的任务上下文中创建 Experiment 根和确定性 Scores。
        await asyncio.to_thread(client.run_experiment, name=run_name, run_name=run_name, data=items,
            task=task, evaluators=[deterministic_scores], max_concurrency=concurrency, metadata=metadata)
        flush()
    else:
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded(item: Any) -> None:
            """关闭 Langfuse 时仍执行完全相同的 HTTP 与评分路径。"""
            async with semaphore:
                await task(item=item)

        await asyncio.gather(*(bounded(item) for item in items))
    # SDK 会过滤 Observation 初始化异常，不能让实验分母随之缩小。
    seen = {row["case_id"] for row in reports}
    for item in items:
        case_id = _case_id(item)
        if case_id not in seen:
            reports.append(_failed_report(case_id, "Experiment 未返回该条执行结果", item=item))
    reports.sort(key=lambda row: row["case_id"])
    summary = {**metadata, **summarize(reports), "suite": suite, "run_name": run_name,
               "elapsed_seconds": round(time.monotonic() - started, 2), "cases": reports}
    summary["acceptance_buckets"] = {
        name: summarize([row for row in reports if bool(row.get("expected_rejection")) == expected_rejection])
        for name, expected_rejection in (("executable", False), ("expected_rejection", True))
    }
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        report.with_suffix(".md").write_text(render_markdown(reports), encoding="utf-8")
    print(f"{run_name}: PASS {summary['passed']}/{summary['total']}, FAIL {summary['failed']}, REJECTED {summary['rejected']}")
    return summary


async def run_local(
    golden_paths: Any, filter_func: str | None, ids: list[str] | None, max_concurrency: int,
    limit: int | None, dry_run: bool, no_judge: bool = False, suite: str = DEFAULT_SUITE,
    report: Path | None = None, *, base_url: str = "http://127.0.0.1:8201", prepare_java: bool = False,
) -> dict[str, Any] | None:
    """读取当前数据集并执行全部选中项，不静默跳过缺失断言或失败用例。"""
    cases = filter_by_ids(load_golden(golden_paths), ids)
    if filter_func:
        cases = filter_by_category(cases, filter_func)
    if limit:
        cases = cases[:limit]
    if dry_run:
        for case in cases:
            print(f"{case.id}: {len(case.turns)} turns")
        return None
    items = [_LocalItem(case, suite).as_item() for case in cases]
    return await _run_items(items, suite=suite, concurrency=max_concurrency, base_url=base_url,
                            prepare_java=prepare_java, report=report)


async def run_eval(
    dataset_name: str, filter_func: str | None, ids: list[str] | None, max_concurrency: int,
    limit: int | None, dry_run: bool, no_judge: bool = False, suite: str = DEFAULT_SUITE,
    *, base_url: str = "http://127.0.0.1:8201", prepare_java: bool = False, report: Path | None = None,
    dataset_version: str | None = None,
) -> dict[str, Any] | None:
    """平台数据集也复用相同执行、断言和退出码，不另设宽松评分路径。"""
    client = get_client()
    if client is None:
        raise ValueError("平台数据集需要启用 Langfuse 并配置项目凭据")
    version = datetime.fromisoformat(dataset_version.replace("Z", "+00:00")) if dataset_version else datetime.now(UTC)
    if version.tzinfo is None:
        raise ValueError("Dataset 版本必须包含时区")
    dataset = await asyncio.to_thread(client.get_dataset, dataset_name, version=version)
    items = select_dataset_items(list(dataset.items), ids)
    if filter_func:
        items = [item for item in items if filter_func in str(_item_value(item, "metadata") or {})]
    if limit:
        items = items[:limit]
    if dry_run:
        for item in items:
            print(item_case(item).id)
        return None
    return await _run_items(items, suite=suite, concurrency=max_concurrency, base_url=base_url,
        prepare_java=prepare_java, report=report,
        metadata_extra={"dataset": dataset_name, "dataset_version": version.isoformat()})


def main() -> int:
    """兼容常用选择参数，任何套件的确定性评分都参与退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="append")
    parser.add_argument("--dataset", default=DATASET_NAME)
    parser.add_argument("--dataset-version", help="平台 Dataset 的带时区 ISO 版本时间")
    parser.add_argument("--suite", choices=SUITES)
    parser.add_argument("--ids")
    parser.add_argument("--filter")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--base-url", default="http://127.0.0.1:8201")
    parser.add_argument("--prepare-java", action="store_true", help="为本地 Java 业务回归准备测试消息")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-judge", action="store_true", help="兼容旧命令；评分始终使用确定性断言")
    parser.add_argument("--fail-under", type=float, default=1.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.concurrency < 1 or not 0 <= args.fail_under <= 1:
        parser.error("concurrency 必须为正数，fail-under 必须在 0 到 1 之间")
    paths = [Path(value) for value in args.local] if args.local else None
    suite = resolve_suite(args.suite, paths, args.dataset if paths is None else None)
    ids = [value.strip() for value in args.ids.split(",") if value.strip()] if args.ids else None
    common = dict(filter_func=args.filter, ids=ids, max_concurrency=args.concurrency, limit=args.limit,
                  dry_run=args.dry_run, no_judge=args.no_judge, suite=suite, report=args.report,
                  base_url=args.base_url, prepare_java=args.prepare_java)
    if paths and args.dataset_version:
        parser.error("本地数据使用内容指纹，--dataset-version 只用于平台 Dataset")
    result = asyncio.run(run_local(paths, **common) if paths else run_eval(args.dataset, dataset_version=args.dataset_version, **common))
    return 0 if result is None or passes_quality_gate(result, args.fail_under) else 1


if __name__ == "__main__":
    raise SystemExit(main())
