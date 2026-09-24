"""把仓库 JSONL fixture 同步为结构化 Langfuse Dataset Item。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from harness.golden import (
    GoldenCase,
    build_overview,
    dataset_expected,
    dataset_input,
    load_golden,
    normalize_case,
)
from scripts.langfuse._public_api import (
    LangfusePublicApi,
    load_dotenv,
    missing_langfuse_config,
    resolve_base_url,
)

load_dotenv()

GOLDEN_PATH = PROJECT_ROOT / "tests" / "fixtures" / "categories"
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures"
logger = logging.getLogger(__name__)
DATASET_NAME = "otc-option-golden"
#: 套件：intent（评路由/意图：冻结用例只调 LLM，回放用例配 mock 后端）/ business（真后端 + 卡片断言 + Judge）
SUITES = ("intent", "business")
INTENT_DIR_NAME = "intent"
BACKENDS = ("mock", "real", "dry-run")
DEFAULT_BACKEND = {"intent": "mock", "business": "real"}


def detect_suite(source: Path) -> str:
    """tests/fixtures/intent/ 下的 fixture 是意图集，其余按业务集。"""
    return "intent" if INTENT_DIR_NAME in source.parts else "business"


#: 与本地确定性评分（langfuse_eval.py --local）共用同一份投影，避免云端 / 本地口径漂移
build_input = dataset_input
build_expected = dataset_expected


def dataset_item_id(dataset_name: str, case_id: str) -> str:
    """Langfuse Item ID 在项目内唯一；不同套件不得相互搬移或覆盖同名案例。"""
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://github.com/GZTL-AI/aigc-langgraph/datasets/{dataset_name}/{case_id}",
    ))


def build_dataset_metadata(cases: list[GoldenCase], *, suite: str) -> dict[str, Any]:
    names = ["response-contains", "response-contains-any", "response-not-contains"]
    if suite == "intent":
        names = ["intent-match"]
        if any(turn.expected.get("instruments") for case in cases for turn in case.turns):
            names.append("instrument-match")
        if any(turn.expected.get("rejection") for case in cases for turn in case.turns):
            names.append("rejection-match")
    return {"suite": suite, "evaluator_names": names}


def _clear_dataset(dataset_name: str, *, base_url: str) -> None:
    """删除数据集全部 Item；base_url 必填，不回落到任何默认地址，避免误删其它项目。"""
    with LangfusePublicApi(
        base_url=base_url,
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
    ) as api:
        item_ids = api.list_dataset_item_ids(dataset_name)
        if not item_ids:
            print(f"Dataset {dataset_name} 当前为空或不存在")
            return
        print(f"清空旧 Dataset：删除 {len(item_ids)} 个 Item")
        for item_id in item_ids:
            api.delete_dataset_item(item_id)


def _require_base_url(override: str | None) -> str:
    base_url = resolve_base_url(override)
    missing = missing_langfuse_config(base_url, require_base_url=True)
    if missing or base_url is None:
        raise RuntimeError(f"缺少 Langfuse 配置: {', '.join(missing)}")
    return base_url


@dataclass(frozen=True)
class PreparedFile:
    path: Path
    dataset_name: str
    items: list[dict[str, Any]]


def _sync_paths(root: Path) -> list[Path]:
    """Only top-level intent and categories fixtures are synced."""
    return sorted(
        [
            *root.joinpath("intent").glob("*.jsonl"),
            *root.joinpath("categories").glob("*.jsonl"),
        ]
    )


def _sync_dataset_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root).parts
    if parts[0] == "intent" and len(parts) == 2:
        return f"intent_{path.stem}"
    if parts[0] == "categories" and len(parts) == 2:
        return path.stem
    raise ValueError(f"Unsupported sync fixture path: {path}")


def _read_rows(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: case must be an object")
        rows.append((line_number, payload))
    if not rows:
        raise ValueError(f"{path}: empty fixture; refusing to archive remote items")
    return rows


def prepare_sync_files(root: Path = FIXTURE_ROOT) -> list[PreparedFile]:
    """Read and validate all sources before the first remote mutation."""
    paths = _sync_paths(root)
    if not paths:
        raise ValueError(f"No sync fixtures found under {root}")
    names: dict[str, Path] = {}
    ids: dict[str, Path] = {}
    prepared: list[PreparedFile] = []
    for path in paths:
        dataset_name = _sync_dataset_name(path, root)
        if dataset_name in names:
            raise ValueError(f"Dataset name conflict: {dataset_name}: {names[dataset_name]} and {path}")
        names[dataset_name] = path
        items: list[dict[str, Any]] = []
        for line_number, payload in _read_rows(path):
            origin = f"{path}:{line_number}"
            case = normalize_case(payload, origin=origin)
            case_id = case.id
            suite = detect_suite(path)
            metadata = _metadata(case, suite=suite, backend=DEFAULT_BACKEND[suite])
            for key in ("reference", "description"):
                if key in payload:
                    metadata[key] = payload[key]
            metadata["fixture_path"] = str(path.relative_to(root)).replace("\\", "/")
            metadata["source_line"] = line_number
            item = {
                "id": f"{dataset_name}:{case_id}",
                "input": build_input(case),
                "expected_output": build_expected(case),
                "metadata": metadata,
            }
            if case_id in ids:
                raise ValueError(f"Duplicate case ID: {case_id}: {ids[case_id]} and {path}")
            ids[case_id] = path
            items.append(item)
        prepared.append(PreparedFile(path, dataset_name, items))
    return prepared


def sync_prepared_files(langfuse: Any, files: list[PreparedFile]) -> None:
    """Upsert every item, then archive stale active items only after all uploads succeed."""
    for source in files:
        langfuse.create_dataset(name=source.dataset_name)
        for item in source.items:
            langfuse.create_dataset_item(
                dataset_name=source.dataset_name, status="ACTIVE", **item
            )
        logger.info("uploaded dataset=%s items=%s", source.dataset_name, len(source.items))
    for source in files:
        current_ids = {item["id"] for item in source.items}
        dataset = langfuse.get_dataset(source.dataset_name)
        stale_ids = sorted(
            item.id for item in dataset.items
            if item.id not in current_ids and item.status == "ACTIVE"
        )
        for item_id in stale_ids:
            langfuse.create_dataset_item(
                dataset_name=source.dataset_name, id=item_id, status="ARCHIVED"
            )
        logger.info("archived dataset=%s items=%s", source.dataset_name, len(stale_ids))


def _metadata(case: GoldenCase, *, suite: str, backend: str) -> dict[str, Any]:
    return {
        "id": case.id,
        "type": case.type,
        "category": case.category,
        "source": case.source,
        "name": case.name,
        "caseNo": case.case_no,
        "scene": case.scene,
        "test_function": case.category,
        "overview": build_overview(case),
        "suite": suite,
        "backend": backend,
        "tags": [tag for tag in (case.category, case.source, suite) if tag],
        "turns": len(case.turns),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync-all", action="store_true", help="同步所有现役 JSONL，每文件一个 Dataset")
    parser.add_argument("--base-url", help="覆盖 LANGFUSE_BASE_URL")
    parser.add_argument("--mode", choices=["overwrite", "append"])
    parser.add_argument("--dataset-name")
    parser.add_argument("--source")
    parser.add_argument(
        "--suite",
        choices=SUITES,
        help="套件；默认按 --source 路径判定（tests/fixtures/intent/ → intent，其余 business）",
    )
    parser.add_argument(
        "--backend",
        choices=BACKENDS,
        help="该数据集设计运行的后端，写入 metadata.backend；默认 intent→mock、business→real",
    )
    args = parser.parse_args()
    if args.sync_all:
        if any((args.source, args.dataset_name, args.mode, args.suite, args.backend)):
            parser.error("--sync-all cannot be combined with manual source, dataset, mode, suite or backend")
        files = prepare_sync_files()
        logger.info("prepared files=%s items=%s", len(files), sum(len(f.items) for f in files))
        if args.dry_run:
            for source_file in files:
                logger.info(
                    "dataset=%s items=%s source=%s",
                    source_file.dataset_name, len(source_file.items), source_file.path,
                )
            return 0
        base_url = _require_base_url(args.base_url)
        from langfuse import Langfuse

        sync_prepared_files(Langfuse(base_url=base_url), files)
        return 0

    source_path_arg = args.source or str(GOLDEN_PATH)
    dataset_name = args.dataset_name or DATASET_NAME
    mode = args.mode or "overwrite"
    suite = args.suite or detect_suite(Path(source_path_arg))
    backend = args.backend or DEFAULT_BACKEND[suite]

    cases = load_golden(Path(source_path_arg))
    print(f"加载 {len(cases)} 条用例：{source_path_arg}（suite={suite} backend={backend}）")

    if args.dry_run:
        single = sum(1 for case in cases if len(case.turns) == 1)
        print(f"单轮：{single}，多轮：{len(cases) - single}")
        for case in cases[:3]:
            input_data = build_input(case)
            turns: list[dict[str, object]] = [input_data]
            sub_scenes = input_data.get("sub_scenes")
            if isinstance(sub_scenes, list):
                turns.extend(scene for scene in sub_scenes if isinstance(scene, dict))
            print(f"  {case.id} [{case.category}] turns={len(turns)}")
            for turn in turns:
                print(f"    send_text: {str(turn.get('send_text') or '')[:80]}")
            print(f"    expectedOutput: {str(build_expected(case))[:160]}")
        print(f"目标 Dataset：{dataset_name} (mode={mode})")
        return 0

    base_url = _require_base_url(args.base_url)
    if mode == "overwrite":
        _clear_dataset(dataset_name, base_url=base_url)

    from langfuse import Langfuse

    langfuse = Langfuse(base_url=base_url)
    dataset = langfuse.create_dataset(
        name=dataset_name, metadata=build_dataset_metadata(cases, suite=suite),
    )
    print(f"创建或复用 Dataset：{dataset.name}")

    success = 0
    failed: list[tuple[str, str]] = []
    for case in cases:
        try:
            langfuse.create_dataset_item(
                id=dataset_item_id(dataset_name, case.id),
                dataset_name=dataset_name,
                input=build_input(case),
                expected_output=build_expected(case),
                metadata=_metadata(case, suite=suite, backend=backend),
            )
            success += 1
        except Exception as exc:  # noqa: BLE001
            failed.append((case.id, str(exc)))

    print(f"完成：{success}/{len(cases)} 上传到 {dataset_name}")
    for case_id, error in failed[:10]:
        print(f"  失败 {case_id}: {error[:160]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
