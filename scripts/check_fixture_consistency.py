#!/usr/bin/env python3
"""tests/fixtures 一致性 CI lint。

校验 README.md §3 的 3 个不变量：
  1. unified_golden.jsonl 的 raw_content 集合 ⊇ golden.jsonl 的 raw_content 集合
     （防止有人加 case 进 golden.jsonl 后忘了跑 merge_golden.py）
  2. 独立历史锚点集中 g001-g030 全部存在，且被 unified 覆盖
  3. 各 fixture 非空、id 唯一且命名遵循职责矩阵约定

退出码：0 一致 / 1 有违反 / 2 文件缺失
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"

FILES = {
    "golden": FIXTURES / "golden.jsonl",
    "unified": FIXTURES / "unified_golden.jsonl",
    "option_qa": FIXTURES / "option_golden.jsonl",
    "business_seeds_snapshot": FIXTURES / "golden_business_seeds_2026-05.jsonl",
    "ticker": FIXTURES / "golden_ticker_2026-05.jsonl",
    "rule_anchors": FIXTURES / "golden_rule_anchors.jsonl",
}

#: README.md §1 职责矩阵约定的 id 前缀正则
ID_PATTERNS = {
    "golden": re.compile(r"^(swap|opt|opt_close|query|close|unknown)-\d{3,4}$"),
    "unified": re.compile(r"^(swap|opt|opt_close|query|close|unknown)-\d{3,4}$"),
    "option_qa": re.compile(r"^opt-\d{3,4}$"),
    "business_seeds_snapshot": re.compile(r"^g\d{3,4}$"),
    "ticker": re.compile(r"^tk\d{3}$"),
    "rule_anchors": re.compile(r"^g\d{3}$"),
}


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _extract_raw(case: dict) -> str:
    """golden / unified 两种 schema 都能抽 raw_content。"""
    if "raw_content" in case:
        return case["raw_content"]
    convo = case.get("conversation") or []
    if convo and isinstance(convo, list):
        return convo[0].get("raw_content", "")
    return ""


# ============================================================
# 校验 1 · unified raw_content ⊇ golden raw_content
# ============================================================


def check_unified_is_superset(golden: list[dict], unified: list[dict]) -> list[str]:
    g_raws = {_extract_raw(c) for c in golden if _extract_raw(c)}
    u_raws = {_extract_raw(c) for c in unified if _extract_raw(c)}
    missing = g_raws - u_raws
    if not missing:
        return []
    errs = [
        f"❌ unified_golden.jsonl 缺 {len(missing)} 条 golden.jsonl 的 raw_content",
        "   修复：python scripts/merge_golden.py（参考 tests/fixtures/README.md §4）",
        "   示例缺失:",
    ]
    for r in list(missing)[:3]:
        errs.append(f"     - {r[:80]}")
    return errs


# ============================================================
# 校验 2 · g001-g030 锚点全在
# ============================================================


def check_anchors_present(golden: list[dict]) -> list[str]:
    """ADR 0015 规则层锚点必须存在。"""
    ids = {c["id"] for c in golden}
    required = {f"g{i:03d}" for i in range(1, 31)}
    missing = required - ids
    if not missing:
        return []
    return [
        f"❌ golden_rule_anchors.jsonl 缺 ADR 0015 规则层锚点: {sorted(missing)}",
        "   这些 case 保留原始 g001-g030 编号，不能删",
        "   参考 ADR 0015 + tests/fixtures/README.md §1",
    ]


# ============================================================
# 校验 3 · id 命名规范
# ============================================================


def check_id_naming(name: str, cases: list[dict]) -> list[str]:
    if not cases:
        return [f"❌ {name} 为空，不能用空文件代替基准数据"]
    counts = Counter(c.get("id", "") for c in cases)
    duplicates = [case_id for case_id, count in counts.items() if count > 1]
    errors = [f"❌ {name} 存在重复 id: {duplicates}"] if duplicates else []
    pattern = ID_PATTERNS[name]
    bad = [c.get("id", "") for c in cases if not pattern.fullmatch(c.get("id", ""))]
    if not bad:
        return errors
    return errors + [
        f"❌ {name} ({FILES[name].name}) 中 {len(bad)} 个 id 不符命名规范 {pattern.pattern}",
        f"   样本: {bad[:5]}",
        "   参考 tests/fixtures/README.md §1 职责矩阵",
    ]


# ============================================================
# 主流程
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="tests/fixtures 一致性 CI lint")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # 文件存在性
    missing_files = [name for name, p in FILES.items() if not p.exists()]
    if missing_files:
        for name in missing_files:
            print(f"ERROR: 缺文件 {FILES[name]}", file=sys.stderr)
        return 2

    data = {name: _load_jsonl(p) for name, p in FILES.items()}

    if args.verbose:
        for name, cases in data.items():
            print(f"  {name:30s} {len(cases):4d} cases  ({FILES[name].name})")

    errors: list[str] = []
    errors.extend(check_unified_is_superset(data["golden"], data["unified"]))
    errors.extend(check_anchors_present(data["rule_anchors"]))
    errors.extend(check_unified_is_superset(data["rule_anchors"], data["unified"]))
    for name in FILES:
        errors.extend(check_id_naming(name, data[name]))

    if not errors:
        print(
            f"✅ tests/fixtures 一致性 OK（{len(data)} 个 fixture · {sum(len(v) for v in data.values())} 总 cases）"
        )
        if args.verbose:
            for name, cases in data.items():
                print(f"   · {name}: {len(cases)} cases")
        return 0

    print(f"❌ 发现 {len([e for e in errors if e.startswith('❌')])} 项违反：")
    print()
    for e in errors:
        print(e)
    return 1


if __name__ == "__main__":
    sys.exit(main())
