"""将期权测试用例 CSV 转换为 Langfuse Dataset JSONL 格式。

输入: /tmp/testcase_期权.csv + /tmp/testcase_期权开平仓口语化.csv
输出: tests/fixtures/option_golden.jsonl

多轮 case 的 CSV 行会合并为单条 JSONL（conversation 数组）。
所有原始字段原样保留，不篡改。

用法:
    python scripts/convert_testcase_to_jsonl.py --dry-run  # 预览
    python scripts/convert_testcase_to_jsonl.py            # 生成
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "tests" / "fixtures" / "option_golden.jsonl"


def _parse_turn_number(raw: str) -> int | None:
    """解析轮次号，如 '1.0' -> 1, '2' -> 2。"""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _extract_quote_info(step_text: str) -> dict:
    """从操作步骤文本中提取引用相关信息。"""
    info = {"has_mention": "@机器人" in step_text, "quote_desc": ""}
    if "引用" in step_text:
        # 提取引用描述
        m = re.search(r"引用[^输入]*", step_text)
        if m:
            info["quote_desc"] = m.group(0)
    return info


def group_rows(rows: list[dict]) -> list[list[dict]]:
    """将 CSV 行按 case 分组。有「案例类型」字段的行视为 case 起点。"""
    groups = []
    current: list[dict] = []

    for i, row in enumerate(rows):
        has_type = bool(row.get("案例类型", "").strip())
        turn = _parse_turn_number(row.get("操作步骤名称（非必填）", ""))

        if has_type and turn == 1:
            # 新的 case 起点
            if current:
                groups.append(current)
            current = [row]
        elif has_type and turn is None:
            # 单轮 case（操作步骤名称可能为空但案例类型有值）
            if current:
                groups.append(current)
            current = [row]
        elif not has_type and current:
            # 续行
            current.append(row)
        elif not has_type and not current:
            # 孤行（数据异常，仍然收录）
            current = [row]
        else:
            current.append(row)

    if current:
        groups.append(current)
    return groups


def build_conversation(group: list[dict]) -> list[dict]:
    """将一个 case 的多行数据构建为 conversation 数组。"""
    turns = []
    for row in group:
        step_name = row.get("操作步骤名称（非必填）", "").strip()
        step_text = row.get("操作步骤", "").strip()
        expected = row.get("预期结果", "").strip()
        test_data = row.get("测试数据", "").strip()
        quote_info = _extract_quote_info(step_text)

        turn_num = _parse_turn_number(step_name)

        turn = {
            "turn": turn_num or 1,
            "user_input": step_text,
            "test_data": test_data,
            "expected": expected,
            "has_mention": quote_info["has_mention"],
            "quote_desc": quote_info["quote_desc"],
        }
        turns.append(turn)
    return turns


def build_case(group: list[dict], case_id: str) -> dict:
    """将一组行构建为单条 JSONL case。"""
    parent = group[0]

    # 标签拆分为数组
    tags_raw = parent.get("标签类型", "")
    tags = [t.strip() for t in tags_raw.replace("\n", ",").split(",") if t.strip()]

    case = {
        "id": case_id,
        "category": parent.get("案例目录", "").strip() or parent.get("测试功能", "").strip(),
        "type": parent.get("案例类型", "").strip(),
        "priority": parent.get("优先级", "").strip(),
        "overview": parent.get("测试概述", "").strip(),
        "precondition": parent.get("前置条件", "").strip(),
        "test_function": parent.get("测试功能", "").strip(),
        "designer": parent.get("设计人员", "").strip(),
        "design_date": parent.get("设计日期", "").strip(),
        "automation_status": parent.get("自动化状态", "").strip(),
        "tags": tags,
        "external_id": parent.get("一站式用例编号(非必填)", "").strip(),
        "is_security_case": parent.get("是否安全用例", "").strip(),
        "notes": parent.get("备注", "").strip(),
        "conversation": build_conversation(group),
    }
    return case


def load_csvs() -> list[dict]:
    """加载所有期权相关 CSV 并统一返回行列表。"""
    all_rows = []

    # 期权 sheet
    path1 = "/tmp/testcase_期权.csv"
    with open(path1, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            all_rows.append(row)

    # 期权开平仓口语化 sheet
    path2 = "/tmp/testcase_期权开平仓口语化.csv"
    with open(path2, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            # 只保留有实质内容的行
            if row.get("操作步骤", "").strip() or row.get("测试概述", "").strip():
                # 补全缺失字段的默认值
                if not row.get("案例类型", "").strip():
                    row["案例类型"] = "正案例"  # 口语化用例默认正案例
                all_rows.append(row)

    return all_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = load_csvs()
    groups = group_rows(rows)
    print(f"加载 {len(rows)} 行 → {len(groups)} 个 case")

    cases = []
    for i, group in enumerate(groups):
        parent = group[0]
        # 生成 id: opt-001, opt-002, ...
        case_id = f"opt-{i+1:03d}"
        case = build_case(group, case_id)
        cases.append(case)

    # 统计
    by_func = {}
    for c in cases:
        func = c["test_function"] or "其他"
        by_func[func] = by_func.get(func, 0) + 1

    print("\n按测试功能:")
    for k, v in sorted(by_func.items()):
        print(f"  {k}: {v}")

    multi = sum(1 for c in cases if len(c["conversation"]) > 1)
    print(f"\n多轮: {multi}, 单轮: {len(cases) - multi}")

    if args.dry_run:
        print(f"\n=== DRY RUN（未写入）===")
        print(f"前 3 个 case 预览:")
        for c in cases[:3]:
            turns = len(c["conversation"])
            print(f"\n  {c['id']} [{c['type']}] {c['overview'][:80]}")
            print(f"  轮次: {turns}, 功能: {c['test_function']}")
            for t in c["conversation"]:
                print(f"    Turn {t['turn']}: {t['user_input'][:100]}")
                print(f"      → {t['expected'][:120]}")
        return

    # 写入
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"\n已写入: {OUTPUT_PATH}  ({len(cases)} 条)")


if __name__ == "__main__":
    main()
