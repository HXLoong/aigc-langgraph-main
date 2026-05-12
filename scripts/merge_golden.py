"""合并 golden.jsonl + option_golden.jsonl → unified_golden.jsonl。

统一 schema：
{
  "id": "g001",
  "category": "swap/place_order",
  "type": "正案例",
  "source": "business_seed",
  "expected": {
    "product_type": "swap",
    "intent": "place_order_request",
    "output": "机器人返回:..."
  },
  "conversation": [
    { "raw_content": "用户原话", "quote_desc": "" }
  ]
}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── category 映射 ──
CATEGORY_MAP = {
    "期权询价": "option/inquiry",
    "期权下单": "option/place_order",
    "期权撤单": "option/cancel",
    "期权\\平仓": "option_close/place",
    "期权\\平仓撤单": "option_close/cancel",
    "期权\\持仓": "option_close/query",
}

# ── product_type 推断 ──
def infer_product_type(category: str) -> str:
    if category.startswith("swap"):
        return "swap"
    if category.startswith("option_close"):
        return "option_close"
    if category.startswith("option"):
        return "option"
    if category.startswith("close"):
        return "option_close"
    return "unknown"


def convert_golden(item: dict) -> dict:
    """golden.jsonl → unified schema。"""
    raw = item["raw_content"]
    conversation = [{"raw_content": raw, "quote_desc": ""}]
    if item.get("quote_content"):
        conversation[0]["quote_desc"] = item["quote_content"]

    expected = dict(item.get("expected", {}))
    expected.setdefault("output", "")

    return {
        "id": item["id"],
        "category": item["category"],
        "type": "正案例",
        "source": item.get("source", "business_seed"),
        "expected": expected,
        "conversation": conversation,
    }


def convert_option(item: dict) -> dict:
    """option_golden.jsonl → unified schema。"""
    cat = item.get("category", "")
    mapped = CATEGORY_MAP.get(cat, cat)
    if not mapped:
        # 从 overview / conversation 推断
        ov = item.get("overview", "")
        if "平仓" in ov or "持仓" in ov:
            mapped = "option_close/place"
        elif "下单" in ov:
            mapped = "option/place_order"
        elif "撤单" in ov:
            mapped = "option/cancel"
        elif "询价" in ov:
            mapped = "option/inquiry"
        else:
            mapped = "option/unknown"

    product_type = infer_product_type(mapped)

    conv = item.get("conversation", [])
    conversation = []
    expected_output = ""
    for turn in conv:
        raw = turn.get("test_data", turn.get("user_input", ""))
        conversation.append({
            "raw_content": raw,
            "quote_desc": turn.get("quote_desc", ""),
        })
        if turn.get("expected"):
            expected_output = turn["expected"]

    return {
        "id": item["id"],
        "category": mapped,
        "type": item.get("type", "正案例"),
        "source": "business_seed",
        "expected": {
            "product_type": product_type,
            "intent": "",
            "output": expected_output,
        },
        "conversation": conversation,
    }


def main() -> None:
    golden_path = ROOT / "tests" / "fixtures" / "golden.jsonl"
    option_path = ROOT / "tests" / "fixtures" / "option_golden.jsonl"
    out_path = ROOT / "tests" / "fixtures" / "unified_golden.jsonl"

    results: list[dict] = []

    # golden.jsonl
    with golden_path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            results.append(convert_golden(json.loads(line)))

    # option_golden.jsonl
    with option_path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            results.append(convert_option(json.loads(line)))

    # 写出
    with out_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"合并完成: {len(results)} 条 → {out_path}")

    # 统计
    from collections import Counter
    cats = Counter(r["category"] for r in results)
    print("\n=== category 分布 ===")
    for k, v in cats.most_common():
        print(f"  {v:3d}  {k}")

    # 检查 conversation 是否为空
    empty_conv = [r["id"] for r in results if not r["conversation"]]
    if empty_conv:
        print(f"\n⚠️ {len(empty_conv)} 条 conversation 为空: {empty_conv[:5]}")


if __name__ == "__main__":
    main()
