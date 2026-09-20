"""把本地 categories fixture 上传到 Langfuse `otc-option-golden` dataset。

input/expected_output 格式与 scripts/langfuse/langfuse_eval.py 的 _LocalItem 一致，
确保上传后 cloud eval 与 local eval 行为完全一致：

  input            = JSON 字符串 {"turns": [{send_text, at_bot, quote_previous}, ...]}
  expected_output  = case.expected_output（自然语言期望）
  metadata         = {id, type, category, source, tags, turns, overview}

用法：
    python scripts/langfuse/upload_golden_to_langfuse.py --dry-run
    python scripts/langfuse/upload_golden_to_langfuse.py                  # overwrite（默认）
    python scripts/langfuse/upload_golden_to_langfuse.py --mode append    # 追加
"""
# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DOTENV = PROJECT_ROOT / ".env"
if _DOTENV.exists():
    for line in _DOTENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and not os.environ.get(k):
            os.environ[k] = v

sys.path.insert(0, str(PROJECT_ROOT))
GOLDEN_PATH = PROJECT_ROOT / "tests" / "fixtures" / "categories"
DATASET_NAME = "otc-option-golden"

from harness.golden import GoldenCase, build_overview, load_golden


def build_input(case: GoldenCase) -> str:
    turns = [
        {
            "send_text": turn.send_text,
            "at_bot": turn.at_bot,
            "quote_previous": turn.quote_previous,
        }
        for turn in case.turns
    ]
    return json.dumps({"turns": turns}, ensure_ascii=False)


def build_expected(case: GoldenCase) -> str:
    """评估层近似期望：expected_output 为空时拼接 response_contains（非业务语义）。"""
    if case.expected_output:
        return case.expected_output
    return "\n".join(line for turn in case.turns for line in turn.response_contains)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mode", choices=["overwrite", "append"], default="overwrite")
    parser.add_argument("--dataset-name", default=DATASET_NAME)
    parser.add_argument("--source", default=str(GOLDEN_PATH))
    args = parser.parse_args()

    cases = load_golden(Path(args.source))
    print(f"加载 {len(cases)} 条 from {args.source}\n")

    if args.dry_run:
        single = sum(1 for c in cases if len(c.turns) == 1)
        multi = len(cases) - single
        print(f"单轮: {single}, 多轮: {multi}")
        print("\n前 3 条预览:")
        for c in cases[:3]:
            inp = json.loads(build_input(c))
            print(f"  {c.id} [{c.category}] turns={len(inp['turns'])}")
            for t in inp["turns"]:
                print(f"    send_text: {t['send_text'][:80]}")
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
                id=c.id,
                dataset_name=args.dataset_name,
                input=build_input(c),
                expected_output=build_expected(c),
                metadata={
                    "id": c.id,
                    "type": c.type,
                    "category": c.category,
                    "source": c.source,
                    "test_function": c.category,
                    "overview": build_overview(c),
                    "tags": [c.category, c.source],
                    "turns": len(c.turns),
                },
            )
            success += 1
            if success % 25 == 0:
                print(f"  已上传 {success}/{len(cases)}...")
        except Exception as e:
            failed.append((c.id, str(e)))

    print(f"\n完成: {success}/{len(cases)} 上传到 {args.dataset_name}")
    if failed:
        print(f"失败 {len(failed)} 条：")
        for fid, err in failed[:10]:
            print(f"  ✗ {fid}: {err[:120]}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
