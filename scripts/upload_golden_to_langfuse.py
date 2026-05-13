"""把本地 tests/fixtures/golden.jsonl 上传到 Langfuse `otc-option-golden` dataset。

input/expected_output 格式与 scripts/langfuse_eval.py 的 _LocalItem 一致，
确保上传后 cloud eval 与 local eval 行为完全一致：

  input            = JSON 字符串 {"turns": [{raw_content, quote_desc}, ...]}
  expected_output  = case["expected"]["output"]（自然语言期望）
  metadata         = {id, type, category, source, tags, turns, overview}

用法：
    python scripts/upload_golden_to_langfuse.py --dry-run
    python scripts/upload_golden_to_langfuse.py                  # overwrite（默认）
    python scripts/upload_golden_to_langfuse.py --mode append    # 追加
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_DOTENV = Path(__file__).resolve().parent.parent / ".env"
if _DOTENV.exists():
    for line in _DOTENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and not os.environ.get(k):
            os.environ[k] = v

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
GOLDEN_PATH = PROJECT_ROOT / "tests" / "fixtures" / "golden.jsonl"
DATASET_NAME = "otc-option-golden"


def load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cases.append(json.loads(line))
    return cases


def _build_overview(case: dict) -> str:
    expected = case.get("expected", {})
    lines = [
        f"ID: {case.get('id', '')}",
        f"类别: {case.get('category', '')}",
        f"用例类型: {case.get('type', '')}",
        f"来源: {case.get('source', '')}",
        f"期望路由: product_type={expected.get('product_type', '')}, intent={expected.get('intent', '')}",
        "对话:",
    ]
    for i, turn in enumerate(case.get("conversation", []), 1):
        raw = turn.get("raw_content", "")
        quote = turn.get("quote_desc", "")
        if quote:
            lines.append(f"  第{i}轮: raw_content={raw}; 引用上一轮机器人回复")
        else:
            lines.append(f"  第{i}轮: raw_content={raw}; 无引用")
    return "\n".join(lines)


def build_input(case: dict) -> str:
    conv = case.get("conversation", [])
    turns = [
        {
            "raw_content": t.get("raw_content", ""),
            "quote_desc": t.get("quote_desc", ""),
        }
        for t in conv
    ]
    return json.dumps({"turns": turns}, ensure_ascii=False)


def build_expected(case: dict) -> str:
    return case.get("expected", {}).get("output", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mode", choices=["overwrite", "append"], default="overwrite")
    parser.add_argument("--dataset-name", default=DATASET_NAME)
    parser.add_argument("--source", default=str(GOLDEN_PATH))
    args = parser.parse_args()

    cases = load_cases(Path(args.source))
    print(f"加载 {len(cases)} 条 from {args.source}\n")

    if args.dry_run:
        single = sum(1 for c in cases if len(c.get("conversation", [])) == 1)
        multi = len(cases) - single
        print(f"单轮: {single}, 多轮: {multi}")
        print(f"\n前 3 条预览:")
        for c in cases[:3]:
            inp = json.loads(build_input(c))
            print(f"  {c['id']} [{c.get('category', '')}] turns={len(inp['turns'])}")
            for t in inp["turns"]:
                print(f"    raw_content: {t['raw_content'][:80]}")
            print(f"    expected: {build_expected(c)[:120]}\n")
        print(f"目标 dataset: {args.dataset_name} (mode={args.mode})")
        return 0

    if args.mode == "overwrite":
        # Langfuse 公共 API 不支持 delete dataset 整体（405）；但支持 delete 单条 item。
        # 策略：列出所有 ACTIVE items → 逐条 delete → 等同于清空 dataset。
        import httpx
        from app.config import get_settings

        settings = get_settings()
        auth = (settings.langfuse_public_key, settings.langfuse_secret_key)
        base = settings.langfuse_base_url

        # 列出所有 items（分页）
        all_ids: list[str] = []
        page = 1
        while True:
            r = httpx.get(
                f"{base}/api/public/dataset-items",
                auth=auth,
                params={"datasetName": args.dataset_name, "limit": 100, "page": page},
                timeout=30,
            )
            if r.status_code != 200:
                print(f"列出 items 失败: {r.status_code} {r.text[:120]}")
                break
            data = r.json().get("data", [])
            if not data:
                break
            all_ids.extend(item.get("id") for item in data if item.get("id"))
            if len(data) < 100:
                break
            page += 1

        if all_ids:
            print(f"清空旧 dataset: 删除 {len(all_ids)} 条 item...")
            deleted = 0
            for item_id in all_ids:
                try:
                    r = httpx.delete(
                        f"{base}/api/public/dataset-items/{item_id}",
                        auth=auth,
                        timeout=30,
                    )
                    if r.status_code == 200:
                        deleted += 1
                except Exception:
                    pass
            print(f"  已删除 {deleted}/{len(all_ids)}")
        else:
            print(f"dataset {args.dataset_name} 当前为空 / 不存在 → 直接创建")

    from langfuse import Langfuse

    lf = Langfuse()
    dataset = lf.create_dataset(name=args.dataset_name)
    print(f"新建/复用数据集: {dataset.name}\n")

    success = 0
    failed: list[tuple[str, str]] = []
    for c in cases:
        try:
            lf.create_dataset_item(
                id=c["id"],
                dataset_name=args.dataset_name,
                input=build_input(c),
                expected_output=build_expected(c),
                metadata={
                    "id": c.get("id", ""),
                    "type": c.get("type", ""),
                    "category": c.get("category", ""),
                    "source": c.get("source", ""),
                    "test_function": c.get("category", ""),
                    "overview": _build_overview(c),
                    "tags": [c.get("category", ""), c.get("source", "")],
                    "turns": len(c.get("conversation", [])),
                },
            )
            success += 1
            if success % 25 == 0:
                print(f"  已上传 {success}/{len(cases)}...")
        except Exception as e:
            failed.append((c.get("id", "?"), str(e)))

    print(f"\n完成: {success}/{len(cases)} 上传到 {args.dataset_name}")
    if failed:
        print(f"失败 {len(failed)} 条：")
        for fid, err in failed[:10]:
            print(f"  ✗ {fid}: {err[:120]}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
