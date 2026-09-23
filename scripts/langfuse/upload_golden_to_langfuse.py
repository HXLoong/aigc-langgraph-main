"""把 categories fixture 上传为结构化 Langfuse Dataset Item。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOTENV = PROJECT_ROOT / ".env"
if DOTENV.exists():
    for line in DOTENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()

sys.path.insert(0, str(PROJECT_ROOT))

from harness.golden import GoldenCase, build_overview, dataset_expected, dataset_input, load_golden

GOLDEN_PATH = PROJECT_ROOT / "tests" / "fixtures" / "categories"
DATASET_NAME = "otc-option-golden"
#: 套件：intent（只调 LLM 评路由/意图，配 mock 后端）/ business（真后端 + 卡片断言 + Judge）
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
    return {"suite": suite, "evaluator_names": names}


def _clear_dataset(dataset_name: str) -> None:
    import httpx

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    base_url = os.environ.get(
        "LANGFUSE_BASE_URL",
        os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
    ).rstrip("/")
    auth = (public_key, secret_key)

    item_ids: list[str] = []
    page = 1
    while True:
        response = httpx.get(
            f"{base_url}/api/public/dataset-items",
            auth=auth,
            params={"datasetName": dataset_name, "limit": 100, "page": page},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"列出 Dataset Items 失败：{response.status_code} {response.text[:200]}"
            )
        data = response.json().get("data", [])
        item_ids.extend(str(item["id"]) for item in data if item.get("id"))
        if len(data) < 100:
            break
        page += 1

    if not item_ids:
        print(f"Dataset {dataset_name} 当前为空或不存在")
        return

    print(f"清空旧 Dataset：删除 {len(item_ids)} 个 Item")
    for item_id in item_ids:
        response = httpx.delete(
            f"{base_url}/api/public/dataset-items/{item_id}",
            auth=auth,
            timeout=30,
        )
        response.raise_for_status()


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mode", choices=["overwrite", "append"], default="overwrite")
    parser.add_argument("--dataset-name", default=DATASET_NAME)
    parser.add_argument("--source", default=str(GOLDEN_PATH))
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
    suite = args.suite or detect_suite(Path(args.source))
    backend = args.backend or DEFAULT_BACKEND[suite]

    cases = load_golden(Path(args.source))
    print(f"加载 {len(cases)} 条用例：{args.source}（suite={suite} backend={backend}）")

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
        print(f"目标 Dataset：{args.dataset_name} (mode={args.mode})")
        return 0

    if args.mode == "overwrite":
        _clear_dataset(args.dataset_name)

    from langfuse import Langfuse

    langfuse = Langfuse()
    dataset = langfuse.create_dataset(
        name=args.dataset_name, metadata=build_dataset_metadata(cases, suite=suite),
    )
    print(f"创建或复用 Dataset：{dataset.name}")

    success = 0
    failed: list[tuple[str, str]] = []
    for case in cases:
        try:
            langfuse.create_dataset_item(
                id=dataset_item_id(args.dataset_name, case.id),
                dataset_name=args.dataset_name,
                input=build_input(case),
                expected_output=build_expected(case),
                metadata=_metadata(case, suite=suite, backend=backend),
            )
            success += 1
        except Exception as exc:  # noqa: BLE001
            failed.append((case.id, str(exc)))

    print(f"完成：{success}/{len(cases)} 上传到 {args.dataset_name}")
    for case_id, error in failed[:10]:
        print(f"  失败 {case_id}: {error[:160]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
