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

INTENT_MAP = {
    "option/inquiry": "new_inquiry",
    "option/place_order": "place_order_from_quote",
    "option/cancel": "request_cancel_order",
    "option_close/query": "close_order_query",
    "option_close/place": "close_order_request",
    "option_close/cancel": "close_order_cancel_request",
    "option_close/confirm": "close_order_confirm",
    "option_close/confirm_cancel": "close_order_cancel_confirm",
}

GOLDEN_CATEGORY_MAP = {
    "swap/place_order_multi": "swap/place_order",
    "swap/ticker_fuzzy": "swap/place_order",
    "swap/ticker_futures": "swap/place_order",
    "option/quick_inquiry": "option/inquiry",
    "option/quick_inquiry_snowball": "option/inquiry",
    "option/standard_inquiry": "option/inquiry",
    "option/extract_inquiry": "option/inquiry",
    "option/confirm_from_quote": "option/confirm",
    "option/unknown": "unknown",
    "option/oral_confirm_unsupported": "unknown",
    "swap/oral_confirm_unsupported": "unknown",
    "noise/digits": "unknown",
    "priority/order_no_over_keyword": "option_close/place",
    "priority/contract_no": "option_close/query",
    "close/query": "option_close/query",
    "close/request": "option_close/place",
    "close/confirm": "option_close/confirm",
    "close/cancel": "option_close/cancel",
    "close/confirm_cancel": "option_close/confirm_cancel",
}

TYPE_MAP = {
    "正案例": "positive",
    "反案例": "negative",
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


def infer_missing_intent(item: dict) -> str:
    expected = item.get("expected", {})
    if expected.get("intent"):
        return expected["intent"]

    product_type = expected.get("product_type", "")
    raw = item.get("raw_content", "")
    category = item.get("category", "")
    if product_type == "unknown":
        return "unknown_intent"
    if product_type == "option_close" and ("状态" in raw or category == "priority/contract_no"):
        return "close_order_order_query"
    return ""


def normalize_golden_category(item: dict) -> str:
    category = item.get("category", "")
    if category in GOLDEN_CATEGORY_MAP:
        return GOLDEN_CATEGORY_MAP[category]
    if category == "option/cancel_request":
        return "option/cancel"
    return category


def infer_option_category(item: dict) -> str:
    cat = item.get("category", "")
    mapped = CATEGORY_MAP.get(cat, cat)
    if mapped:
        return mapped

    raw_text = " ".join(
        turn.get("test_data", "") or turn.get("user_input", "")
        for turn in item.get("conversation", [])
    )
    close_action_words = ("平一半", "全平", "平剩", "平掉", "平仓剩", "留", "平200", "平100", "平300")
    if ("持仓" in raw_text or "可平" in raw_text) and not any(
        word in raw_text for word in close_action_words
    ):
        return "option_close/query"
    if any(word in raw_text for word in close_action_words) or (
        "平" in raw_text and "持仓" not in raw_text and "可平" not in raw_text
    ):
        return "option_close/place"

    text = " ".join(
        [
            item.get("overview", ""),
            item.get("test_function", ""),
            " ".join(
                " ".join(
                    [
                        turn.get("test_data", ""),
                        turn.get("user_input", ""),
                        turn.get("expected", ""),
                    ]
                )
                for turn in item.get("conversation", [])
            ),
        ]
    )
    if "平仓" in text or "平仓申请" in text or "平剩" in text or "全平" in text:
        return "option_close/place"
    if "持仓" in text or "可平" in text:
        return "option_close/query"
    if "撤单" in text or "取消" in text:
        return "option/cancel"
    if "下单" in text:
        return "option/place_order"
    if "询价" in text:
        return "option/inquiry"
    return "option/unknown"


def convert_golden(item: dict) -> dict:
    """golden.jsonl → unified schema。"""
    raw = item["raw_content"]
    category = normalize_golden_category(item)
    conversation = [{"raw_content": raw, "quote_desc": ""}]
    if item.get("quote_content"):
        conversation[0]["quote_desc"] = item["quote_content"]

    expected = dict(item.get("expected", {}))
    intent = infer_missing_intent(item)
    if intent:
        expected["intent"] = intent
    expected.setdefault("output", "")

    return {
        "id": item["id"],
        "category": category,
        "type": TYPE_MAP.get(item.get("type", ""), "positive"),
        "source": item.get("source", "business_seed"),
        "expected": expected,
        "conversation": conversation,
    }


def convert_option(item: dict) -> dict:
    """option_golden.jsonl → unified schema。"""
    mapped = infer_option_category(item)

    product_type = infer_product_type(mapped)

    conv = item.get("conversation", [])
    conversation = []
    expected_parts = []
    for turn in conv:
        raw = turn.get("test_data", turn.get("user_input", ""))
        conversation.append({
            "raw_content": raw,
            "quote_desc": turn.get("quote_desc", ""),
        })
        if turn.get("expected"):
            if len(conv) > 1:
                expected_parts.append(f"[第{turn.get('turn', len(expected_parts) + 1)}轮] {turn['expected']}")
            else:
                expected_parts.append(turn["expected"])

    return {
        "id": item["id"],
        "category": mapped,
        "type": TYPE_MAP.get(item.get("type", ""), item.get("type", "positive")),
        "source": "business_seed",
        "expected": {
            "product_type": product_type,
            "intent": INTENT_MAP.get(mapped, ""),
            "output": "\n".join(expected_parts),
        },
        "conversation": conversation,
    }


def assign_ids(results: list[dict]) -> None:
    counters = {"opt": 0, "swap": 0, "unknown": 0}
    for item in results:
        product_type = item.get("expected", {}).get("product_type")
        if product_type in {"option", "option_close"}:
            prefix = "opt"
        elif product_type == "swap":
            prefix = "swap"
        else:
            prefix = "unknown"
        counters[prefix] += 1
        item["id"] = f"{prefix}-{counters[prefix]:03d}"


def sort_by_id(results: list[dict]) -> list[dict]:
    order = {"opt": 0, "swap": 1, "unknown": 2}

    def key(item: dict) -> tuple[int, int]:
        prefix, number = item["id"].split("-", 1)
        return order[prefix], int(number)

    return sorted(results, key=key)


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

    assign_ids(results)
    results = sort_by_id(results)

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
