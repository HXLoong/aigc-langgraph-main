"""将 JSONL 测试集导出为每个发送步骤一行的中文 CSV（仅依赖标准库）。

用法（默认路径相对于仓库，显式参数相对于当前工作目录）：
    python scripts/convert_jsonl_to_csv.py
    python scripts/convert_jsonl_to_csv.py --input tests/fixtures/categories/example.jsonl
    python scripts/convert_jsonl_to_csv.py --input tests/fixtures/categories --output-dir out
    python scripts/convert_jsonl_to_csv.py --dry-run

每个 JSONL 输出一个同名 CSV，默认放在输入目录的 csv/ 下，重复执行覆盖输出。
目录模式只扫描直接子级。空文件生成仅有表头的 CSV；空白行不作为用例。

原始 Excel 的“测试数据”对应 send_text/raw_content，不等同于含操作说明的
“操作步骤描述”。categories 的询价、开仓用例已改为场景和响应断言，部分输入
也已调整；平仓仍使用 conversation，并在 expected.output 中保留汇总预期。
无输入的等待通知步骤可能只存在于该汇总文本中，不能按“第 N 轮”猜测拆分。

本脚本只读取当前 JSONL，不读取 Excel 或其他 golden 文件，不恢复旧输入、
删除的步骤或缺失的概述/前置条件。子场景不继承主场景断言。引用布尔值仅保留
显式字段，不从 quote_desc 推导。未映射字段保留为扩展 JSON。
字符串原样保存，数组/对象使用中文 JSON，布尔值为 true/false，null 与缺失分开。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "categories"
SOURCE_PREFIX = "json/golden_case_raw/"
CASE_COLUMNS = {
    "id": "用例ID",
    "caseNo": "用例编号",
    "name": "用例名称",
    "category": "案例目录",
    "type": "案例类型",
    "source": "数据来源",
}
STEP_COLUMNS = {
    "scene": "步骤场景",
    "at_bot": "是否@机器人",
    "quote_previous": "是否引用上一条",
    "quote_desc": "引用说明",
    "expected": "步骤级预期",
    "response_contains": "响应必须包含",
    "response_contains_any": "响应包含任一",
    "response_not_contains": "响应不得包含",
}
FIELDNAMES = [
    "来源文件",
    "源行号",
    *CASE_COLUMNS.values(),
    "需求场景",
    "操作步骤序号",
    "步骤场景",
    "测试数据",
    "是否@机器人",
    "是否引用上一条",
    "引用说明",
    "用例级预期",
    "步骤级预期",
    "响应必须包含",
    "响应包含任一",
    "响应不得包含",
    "用例其他字段",
    "步骤其他字段",
]


def cell(value: Any) -> str:
    """仅调用于已存在的字段，保留显式 null、false 和字符串空白。"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def extra_fields(record: dict[str, Any], known: set[str]) -> str:
    extra = {key: value for key, value in record.items() if key not in known}
    return cell(extra) if extra else ""


def validate_step(step: Any, text_key: str, *, root: bool = False) -> None:
    if not isinstance(step, dict):
        raise ValueError("步骤必须是对象")
    other_text = "raw_content" if text_key == "send_text" else "send_text"
    if other_text in step or "conversation" in step or (not root and "sub_scenes" in step):
        raise ValueError("步骤结构冲突或包含不支持的嵌套步骤")
    if not isinstance(step.get(text_key), str) or not step[text_key].strip():
        raise ValueError(f"步骤缺少非空字符串 {text_key}")


def expand_case(case: dict[str, Any], path: Path, line_number: int) -> list[dict[str, str]]:
    """按当前步骤顺序展开；用例汇总字段与步骤字段保持各自语义。"""
    conversation = "conversation" in case
    case_known = set(CASE_COLUMNS)
    if conversation:
        if any(key in case for key in ("send_text", "raw_content", "sub_scenes")):
            raise ValueError("conversation 与场景结构冲突")
        steps = case["conversation"]
        if not isinstance(steps, list) or not steps:
            raise ValueError("conversation 必须是非空数组")
        text_key = "raw_content"
        case_known.update({"conversation", "expected"})
    else:
        if "send_text" not in case:
            raise ValueError("不支持的用例结构：需要 send_text 或 conversation")
        children = case.get("sub_scenes", [])
        if not isinstance(children, list):
            raise ValueError("sub_scenes 必须是数组")
        steps = [case, *children]
        text_key = "send_text"
        case_known.update({"send_text", "sub_scenes", *STEP_COLUMNS})

    metadata = {column: cell(case[key]) for key, column in CASE_COLUMNS.items() if key in case}
    source = case.get("source")
    metadata.update(
        {
            "来源文件": path.name,
            "源行号": str(line_number),
            "需求场景": source[len(SOURCE_PREFIX) :]
            if isinstance(source, str) and source.startswith(SOURCE_PREFIX)
            else "",
            "用例其他字段": extra_fields(case, case_known),
        }
    )
    if conversation and "expected" in case:
        metadata["用例级预期"] = cell(case["expected"])

    rows = []
    for number, step in enumerate(steps, 1):
        try:
            validate_step(step, text_key, root=not conversation and number == 1)
        except ValueError as exc:
            raise ValueError(f"步骤 {number}: {exc}") from exc
        row = dict.fromkeys(FIELDNAMES, "")
        row.update(metadata)
        row.update({column: cell(step[key]) for key, column in STEP_COLUMNS.items() if key in step})
        row["操作步骤序号"] = str(number)
        row["测试数据"] = step[text_key]
        # 主场景与用例是同一个对象，未知字段只在用例其他字段保存一次。
        if conversation or number > 1:
            row["步骤其他字段"] = extra_fields(step, {text_key, *STEP_COLUMNS})
        rows.append(row)
    return rows


def reject_constant(value: str) -> None:
    raise ValueError(f"不支持非标准 JSON 常量 {value}")


def load_rows(path: Path) -> tuple[int, list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    case_count = 0
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                case = json.loads(line, parse_constant=reject_constant)
                if not isinstance(case, dict):
                    raise ValueError("用例必须是 JSON 对象")
                rows.extend(expand_case(case, path, line_number))
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            case_count += 1
    return case_count, rows


def find_inputs(source: Path) -> list[Path]:
    if source.is_dir():
        paths = sorted(p for p in source.glob("*.jsonl") if p.is_file())
        if not paths:
            raise ValueError(f"目录中没有 JSONL 文件: {source}")
        return paths
    if not source.is_file():
        raise ValueError(f"输入不存在或不是文件/目录: {source}")
    if source.suffix.lower() != ".jsonl":
        raise ValueError(f"输入文件必须为 .jsonl: {source}")
    return [source]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """同目录临时文件写完关闭后替换，Windows 上同样不暴露半截输出。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="JSONL 文件或目录")
    parser.add_argument("--output-dir", type=Path, help="默认：输入目录/csv")
    parser.add_argument("--dry-run", action="store_true", help="仅校验并统计，不写文件")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        paths = find_inputs(args.input)
        output_dir = args.output_dir if args.output_dir is not None else paths[0].parent / "csv"
        # 整批先验证，后续文件有坏行时不修改任何 CSV。
        prepared = [(path, *load_rows(path)) for path in paths]
        for path, count, rows in prepared:
            target = output_dir / f"{path.stem}.csv"
            if not args.dry_run:
                write_csv(target, rows)
            logger.info(
                "input=%s cases=%s steps=%s output=%s dry_run=%s",
                path,
                count,
                len(rows),
                target,
                args.dry_run,
            )
        logger.info(
            "files=%s cases=%s steps=%s dry_run=%s",
            len(prepared),
            sum(count for _, count, _ in prepared),
            sum(len(rows) for _, _, rows in prepared),
            args.dry_run,
        )
    except (OSError, ValueError) as exc:
        logger.error("conversion_failed error=%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
