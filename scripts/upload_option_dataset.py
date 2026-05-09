"""上传期权 golden JSONL 到 Langfuse Dataset。

input 列存储结构化数据（机器可读）：
  {"turns": [{"raw_content": "...", "has_mention": true/false, "quote_desc": "..."}]}

expected_output 列保留原始自然语言期望（Judge LLM 对照判断）。

用法:
    python scripts/upload_option_dataset.py --dry-run
    python scripts/upload_option_dataset.py
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
JSONL_PATH = PROJECT_ROOT / "tests" / "fixtures" / "option_golden.jsonl"
DATASET_NAME = "otc-option-golden"


def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_input(case: dict) -> str:
    """构建结构化 input，task 函数可直接 json.loads 解析。"""
    turns = []
    for t in case["conversation"]:
        # 从 user_input 描述文本中提取真正的 raw_content
        # 原格式: "用户在微信群中@机器人输入询价指令：\n"600519.SH,欧式看涨,1M,80%""
        raw = t.get("test_data", "")
        if not raw:
            raw = t.get("user_input", "")

        turn_data = {
            "raw_content": raw,
            "has_mention": t.get("has_mention", False),
        }
        if t.get("quote_desc"):
            turn_data["quote_desc"] = t["quote_desc"]
        turns.append(turn_data)

    return json.dumps({"turns": turns}, ensure_ascii=False)


def build_expected(case: dict) -> str:
    """构建 expected_output，保留原始自然语言期望。"""
    parts = []
    for t in case["conversation"]:
        if t["expected"]:
            turns_count = len(case["conversation"])
            if turns_count > 1:
                parts.append(f"[第{t['turn']}轮] {t['expected']}")
            else:
                parts.append(t["expected"])
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dataset-name", default=DATASET_NAME)
    args = parser.parse_args()

    cases = load_cases(JSONL_PATH)
    print(f"加载 {len(cases)} 条期权 case\n")

    if args.dry_run:
        single = sum(1 for c in cases if len(c["conversation"]) == 1)
        multi = len(cases) - single
        print(f"单轮: {single}, 多轮: {multi}")
        print(f"\n前 3 条预览:\n")
        for c in cases[:3]:
            inp = json.loads(build_input(c))
            exp = build_expected(c)
            print(f"  {c['id']} [{c['type']}] {c['overview'][:80]}")
            print(f"  turns: {len(inp['turns'])}")
            for t in inp["turns"]:
                print(f"    raw_content: {t['raw_content'][:100]}")
                print(f"    has_mention: {t['has_mention']}")
            print(f"  expected: {exp[:200]}")
            print()
        return

    # 删除旧数据集后重建
    import httpx
    from app.config import get_settings

    settings = get_settings()
    try:
        url = f"{settings.langfuse_host}/api/public/v2/datasets/{args.dataset_name}"
        resp = httpx.delete(
            url,
            auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            timeout=30,
        )
        if resp.status_code == 200:
            print(f"已删除旧数据集: {args.dataset_name}")
    except Exception as e:
        print(f"删除旧数据集失败: {e}")

    from langfuse import Langfuse

    lf = Langfuse()
    dataset = lf.create_dataset(name=args.dataset_name)
    print(f"新建数据集: {dataset.name}")

    success = 0
    for c in cases:
        try:
            lf.create_dataset_item(
                id=c["id"],
                dataset_name=args.dataset_name,
                input=build_input(c),
                expected_output=build_expected(c),
                metadata={
                    "type": c["type"],
                    "priority": c["priority"],
                    "category": c.get("category", ""),
                    "test_function": c.get("test_function", ""),
                    "overview": c.get("overview", ""),
                    "precondition": c.get("precondition", ""),
                    "tags": c.get("tags", []),
                    "turns": len(c["conversation"]),
                    "designer": c.get("designer", ""),
                    "design_date": c.get("design_date", ""),
                },
            )
            success += 1
            if success % 20 == 0:
                print(f"  已上传 {success}/{len(cases)}...")
        except Exception as e:
            print(f"  ✗ {c['id']} 失败: {e}")

    print(f"\n完成: {success}/{len(cases)} 条 → {args.dataset_name}")


if __name__ == "__main__":
    main()
