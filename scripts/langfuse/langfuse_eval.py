"""经 HTTP 执行数据集并关联 Langfuse Experiment；评分由平台 JS Rule 完成。"""
from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
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
from harness.http_evaluation import run_case
from harness.langfuse_client import experiment_item_trace, flush, get_client
from harness.version import ASSERTION_VERSION

DATASET_NAME = "biz/option_inquiry"
SUITES = ("intent", "business")
DEFAULT_SUITE = "business"


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


def _failed_report(case_id: str, reason: str, *, item: Any = None) -> dict[str, Any]:
    """基础设施异常也保留一个失败条目，不能从统计分母消失。"""
    return {"case_id": case_id, "id": case_id, "status": "FAIL", "passed": False,
            "input": _item_value(item, "input", {}),
            "expected_output": _item_value(item, "expected_output", {}),
            "turns": [], "failure": {"kind": "execution_error", "error": reason}}


async def _run_items(
    items: list[Any], *, suite: str, concurrency: int, base_url: str,
    prepare_java: bool, metadata_extra: dict[str, str] | None = None,
) -> None:
    """提交 Experiment 输出；Langfuse 后台 JS Evaluation Rule 异步产生 Score。"""
    if not items:
        raise ValueError("没有选中的可执行数据集条目")
    run_name = f"{suite}-eval-{time.strftime('%Y%m%d-%H%M%S')}"
    client = get_client()
    if client is None:
        raise ValueError("Experiment 需要启用 Langfuse 并配置项目凭据")

    async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        """捕获单个用例故障，使 JS Rule 能看到失败输出。"""
        case_id = _case_id(item)
        try:
            with experiment_item_trace(active=True):
                output = await run_langgraph_pipeline(item=item, suite=suite, base_url=base_url,
                                                      run_name=run_name, prepare_java=prepare_java)
        except Exception as exc:
            output = _failed_report(case_id, f"{type(exc).__name__}: {exc}", item=item)
        return output
    # SDK 创建 Experiment 根并保存输出，Score 由平台 JS Rule 异步生成。
    result = await asyncio.to_thread(client.run_experiment, name=run_name, run_name=run_name, data=items,
        task=task, max_concurrency=concurrency, metadata=metadata_extra or {})
    flush()
    print(f"实验已提交: {getattr(result, 'name', run_name)}；Score 由 Langfuse JS Evaluation Rule 异步生成")


async def run_local(
    golden_paths: Any, filter_func: str | None, ids: list[str] | None, max_concurrency: int,
    limit: int | None, dry_run: bool, no_judge: bool = False, suite: str = DEFAULT_SUITE,
    *, base_url: str = "http://127.0.0.1:8201", prepare_java: bool = False,
) -> None:
    """读取本地 fixture，执行后上传为 Langfuse Experiment。"""
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
    await _run_items(items, suite=suite, concurrency=max_concurrency, base_url=base_url,
                     prepare_java=prepare_java)


async def run_eval(
    dataset_name: str, filter_func: str | None, ids: list[str] | None, max_concurrency: int,
    limit: int | None, dry_run: bool, no_judge: bool = False, suite: str = DEFAULT_SUITE,
    *, base_url: str = "http://127.0.0.1:8201", prepare_java: bool = False,
    dataset_version: str | None = None,
) -> None:
    """执行平台 Dataset；评分由匹配的 JS Evaluation Rule 完成。"""
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
    await _run_items(items, suite=suite, concurrency=max_concurrency, base_url=base_url,
        prepare_java=prepare_java,
        metadata_extra={"dataset": dataset_name, "dataset_version": version.isoformat()})


def main() -> int:
    """兼容常用选择参数，只负责执行并提交 Experiment。"""
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
    parser.add_argument("--no-judge", action="store_true", help="兼容旧命令；脚本不调用 Judge")
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("concurrency 必须为正数")
    paths = [Path(value) for value in args.local] if args.local else None
    suite = resolve_suite(args.suite, paths, args.dataset if paths is None else None)
    ids = [value.strip() for value in args.ids.split(",") if value.strip()] if args.ids else None
    common = dict(filter_func=args.filter, ids=ids, max_concurrency=args.concurrency, limit=args.limit,
                  dry_run=args.dry_run, no_judge=args.no_judge, suite=suite,
                  base_url=args.base_url, prepare_java=args.prepare_java)
    if paths and args.dataset_version:
        parser.error("本地数据使用内容指纹，--dataset-version 只用于平台 Dataset")
    asyncio.run(run_local(paths, **common) if paths else run_eval(args.dataset, dataset_version=args.dataset_version, **common))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
