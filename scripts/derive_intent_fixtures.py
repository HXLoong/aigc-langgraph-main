"""从 categories 业务集派生意图集草稿（tests/fixtures/intent/ 的输入来源）。

用法：
    python scripts/derive_intent_fixtures.py --dry-run
    python scripts/derive_intent_fixtures.py --out tmp/intent_drafts
    python scripts/derive_intent_fixtures.py --only-labeled --out tests/fixtures/intent

只做确定性搬运，不猜标签：
- product_type 优先沿用原 expected，否则按 category / 文件名前缀派生（option_close / option / swap）
- intent 只沿用原 expected.intent；未标注的轮 intent 留空并写 review.pending，草稿需业务方
  review 后才能进 tests/fixtures/intent/（lint 会拒绝空 intent）
- 卡片文本断言（response_*）一律丢弃：那是业务集的职责
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "tests" / "fixtures" / "categories"
DEFAULT_OUT = REPO_ROOT / "tmp" / "intent_drafts"

INTENT_ID_PREFIX = "intent-"
_TURN_INPUT_KEYS = ("scene", "send_text", "at_bot", "quote_previous")
_PRODUCT_PREFIXES = (("option_close", "option_close"), ("option", "option"), ("swap", "swap"))


def product_type_for(category: str, expected: dict[str, Any]) -> str:
    """原 expected.product_type 优先；否则按 category 前缀派生。"""
    declared = expected.get("product_type")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    for prefix, product in _PRODUCT_PREFIXES:
        if category.startswith(prefix):
            return product
    raise ValueError(f"cannot infer product_type from category {category!r}")


def _turn(obj: dict[str, Any], product_type: str) -> tuple[dict[str, Any], bool]:
    """搬运一轮输入 + 意图标签；返回 (turn, labeled)。"""
    turn: dict[str, Any] = {key: obj[key] for key in _TURN_INPUT_KEYS if key in obj}
    expected = obj.get("expected") if isinstance(obj.get("expected"), dict) else {}
    intent = expected.get("intent")
    intent = intent.strip() if isinstance(intent, str) else ""
    turn_product = expected.get("product_type")
    turn["expected"] = {
        "product_type": turn_product.strip() if isinstance(turn_product, str) and turn_product.strip() else product_type,
        "intent": intent,
    }
    return turn, bool(intent)


def derive_case(obj: dict[str, Any], *, source_stem: str) -> dict[str, Any]:
    """一条业务集 case → 意图集 case（草稿）。"""
    case_no = str(obj.get("caseNo") or obj.get("id") or "").strip()
    if not case_no:
        raise ValueError(f"{source_stem}: caseNo/id is required")
    category = str(obj.get("category") or source_stem)
    expected = obj.get("expected") if isinstance(obj.get("expected"), dict) else {}
    product_type = product_type_for(category, expected)

    first, labeled = _turn(obj, product_type)
    unlabeled: list[int] = [] if labeled else [1]
    sub_scenes: list[dict[str, Any]] = []
    for index, sub_scene in enumerate(obj.get("sub_scenes") or [], start=2):
        if not isinstance(sub_scene, dict):
            raise ValueError(f"{source_stem}#{case_no}: sub_scenes[{index - 2}] must be an object")
        turn, labeled = _turn(sub_scene, product_type)
        sub_scenes.append(turn)
        if not labeled:
            unlabeled.append(index)

    case: dict[str, Any] = {
        "caseNo": f"{INTENT_ID_PREFIX}{product_type}-{case_no}",
        "name": str(obj.get("name") or case_no),
        "category": f"intent/{product_type}",
        "type": obj.get("type") if obj.get("type") in ("positive", "negative") else "positive",
        "source": f"derived:{source_stem}#{case_no}",
        **first,
        "sub_scenes": sub_scenes,
    }
    if unlabeled:
        case["review"] = {"status": "pending", "unlabeled_turns": unlabeled}
    return case


def _iter_source(source: Path) -> list[tuple[str, dict[str, Any]]]:
    paths = sorted(source.glob("*.jsonl")) if source.is_dir() else [source]
    records: list[tuple[str, dict[str, Any]]] = []
    for path in paths:
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{line_number}: case must be an object")
            records.append((path.stem, obj))
    return records


def write_drafts(source: Path, out: Path, *, only_labeled: bool) -> dict[str, int]:
    """按产品分文件写出草稿；返回 {product: 条数}。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for stem, obj in _iter_source(source):
        case = derive_case(obj, source_stem=stem)
        if only_labeled and "review" in case:
            continue
        product = case["category"].split("/", 1)[1]
        grouped.setdefault(product, []).append(case)
    out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, int] = {}
    for product, cases in sorted(grouped.items()):
        target = out / f"{product}.jsonl"
        target.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases),
            encoding="utf-8",
        )
        summary[product] = len(cases)
        logger.info("wrote product=%s cases=%d path=%s", product, len(cases), target)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="categories 目录或单个 JSONL")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录，按产品写 <product>.jsonl")
    parser.add_argument("--only-labeled", action="store_true", help="只输出逐轮 intent 已标注的 case")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.dry_run:
        counter: Counter[str] = Counter()
        pending = 0
        for stem, obj in _iter_source(args.source):
            case = derive_case(obj, source_stem=stem)
            counter[case["category"]] += 1
            pending += "review" in case
        for category, count in sorted(counter.items()):
            logger.info("%s: %d", category, count)
        logger.info("pending review (unlabeled intent): %d / %d", pending, sum(counter.values()))
        return 0

    summary = write_drafts(args.source, args.out, only_labeled=args.only_labeled)
    logger.info("done: %s", summary or "no cases written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
