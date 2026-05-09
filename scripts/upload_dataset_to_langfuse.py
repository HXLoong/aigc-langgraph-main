"""上传 golden.jsonl 到 Langfuse Dataset。

用法：
    # 预览
    python scripts/upload_dataset_to_langfuse.py --dry-run

    # 上传
    python scripts/upload_dataset_to_langfuse.py

    # 追加（默认覆盖同名 dataset）
    python scripts/upload_dataset_to_langfuse.py --mode append
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
GOLDEN_PATH = PROJECT_ROOT / "tests" / "fixtures" / "golden.jsonl"
sys.path.insert(0, str(PROJECT_ROOT))


def load_golden(path: Path) -> list[dict]:
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  ⚠ 跳过无效行: {line[:80]}...")
    return cases


def main():
    parser = argparse.ArgumentParser(description="上传 golden.jsonl 到 Langfuse Dataset")
    parser.add_argument("--dry-run", action="store_true", help="只预览")
    parser.add_argument("--mode", choices=["overwrite", "append"], default="overwrite")
    parser.add_argument("--dataset-name", default="otc-agent-golden", help="Dataset 名称")
    args = parser.parse_args()

    cases = load_golden(GOLDEN_PATH)
    print(f"从 golden.jsonl 加载 {len(cases)} 条用例\n")

    if args.dry_run:
        for c in cases:
            print(f"  {c['id']:8s}  {c['category']:35s}  {c['raw_content'][:60]}")
        print(f"\n将上传到 dataset: {args.dataset_name} (mode={args.mode})")
        return

    from langfuse import Langfuse
    lf = Langfuse()

    # 数据集覆盖：先删后建
    if args.mode == "overwrite":
        try:
            # Langfuse SDK 没有直接 delete dataset 的方法，用 REST API
            import httpx
            from app.config import get_settings
            settings = get_settings()
            url = f"{settings.langfuse_host}/api/public/v2/datasets/{args.dataset_name}"
            resp = httpx.delete(
                url,
                auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
                timeout=30,
            )
            if resp.status_code == 200:
                print(f"已删除旧数据集: {args.dataset_name}")
        except Exception as e:
            print(f"删除旧数据集失败（可能不存在）: {e}")

    # 创建/获取数据集
    dataset = lf.create_dataset(name=args.dataset_name)
    print(f"数据集: {dataset.name}")

    # 逐条上传
    success = 0
    for c in cases:
        # input: 用户消息
        inp = c.get("raw_content", "")
        if c.get("quote_content"):
            inp = f"[引用消息] {c['quote_content']}\n[输入消息] {inp}"

        # expected_output: 期望的识别结果
        expected = c.get("expected", {})

        try:
            lf.create_dataset_item(
                id=c.get("id"),
                dataset_name=args.dataset_name,
                input=inp,
                expected_output=expected,
                metadata={
                    "category": c.get("category", ""),
                },
            )
            success += 1
            if success % 10 == 0:
                print(f"  已上传 {success}/{len(cases)}...")
        except Exception as e:
            print(f"  ✗ {c.get('id', '?')} 失败: {e}")

    print(f"\n完成: {success}/{len(cases)} 条上传到 {args.dataset_name}")


if __name__ == "__main__":
    main()
