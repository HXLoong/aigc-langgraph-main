"""将 JSONL 测试集直接转为一个 Excel 工作簿，每个 JSONL 对应一个工作表。

用法：
    python scripts/convert_jsonl_to_excel.py
    python scripts/convert_jsonl_to_excel.py --input tests/fixtures/categories
    python scripts/convert_jsonl_to_excel.py --input example.jsonl --output example.xlsx
    python scripts/convert_jsonl_to_excel.py --dry-run

默认读取 ``tests/fixtures/categories``，输出该目录下的“黄金数据集.xlsx”。
目录模式只扫描直接子级 JSONL，按文件名排序。每张表的列由对应
JSONL 实际出现的顶层字段按首次出现顺序组成；对象、数组、布尔值和 null
使用 JSON 文本写入单元格，不展开 ``sub_scenes`` 等嵌套字段。
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import convert_csv_to_excel as excel_converter
import convert_jsonl_to_csv as jsonl_converter
from openpyxl import Workbook

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "tests" / "fixtures" / "categories"


def _cell(value: object) -> str:
    """字符串原样保留，其余值使用 JSON 文本保真。"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _read_jsonl(path: Path, title: str) -> excel_converter.CsvTable:
    records: list[dict[str, object]] = []
    headers: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, parse_constant=jsonl_converter.reject_constant)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: JSON 读取失败: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: 每行必须是 JSON 对象")
            records.append(record)
            for key in record:
                if key not in seen:
                    seen.add(key)
                    headers.append(key)

    if not records:
        raise ValueError(f"JSONL 为空，无字段可生成 Excel: {path}")
    if len(headers) > excel_converter.MAX_COLUMNS:
        raise ValueError(f"{path}: 超过 Excel 列数限制 {excel_converter.MAX_COLUMNS}")
    if len(records) + 1 > excel_converter.MAX_ROWS:
        raise ValueError(f"{path}: 超过 Excel 行数限制 {excel_converter.MAX_ROWS}")

    rows = [headers]
    for row_number, record in enumerate(records, 2):
        row = [_cell(record[key]) if key in record else "" for key in headers]
        for column, value in enumerate(row, 1):
            excel_converter.validate_cell(value, f"{path}: 记录 {row_number - 1}, 列 {column}")
        rows.append(row)
    return excel_converter.CsvTable(path=path, title=title, rows=rows)


def _prepare_tables(paths: list[Path]) -> list[excel_converter.CsvTable]:
    """每个 JSONL 以自身实际字段生成一张表。"""
    used_titles: set[str] = set()
    tables: list[excel_converter.CsvTable] = []
    for path in paths:
        title = excel_converter.sheet_name(path.stem, used_titles)
        tables.append(_read_jsonl(path, title))
    return tables


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="JSONL 文件或目录")
    parser.add_argument("--output", type=Path, help="输出 .xlsx 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅校验并统计，不写文件")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    workbook: Workbook | None = None
    try:
        source = args.input.resolve()
        paths = jsonl_converter.find_inputs(source)
        output = (
            args.output.resolve()
            if args.output is not None
            else (source / "黄金数据集.xlsx" if source.is_dir() else source.with_suffix(".xlsx"))
        )
        if output.suffix.lower() != ".xlsx":
            raise ValueError(f"输出文件必须为 .xlsx: {output}")

        tables = _prepare_tables(paths)
        for path, table in zip(paths, tables, strict=True):
            logger.info(
                "input=%s sheet=%s rows=%s columns=%s dry_run=%s",
                path,
                table.title,
                len(table.rows) - 1,
                len(table.rows[0]),
                args.dry_run,
            )
        if not args.dry_run:
            workbook = excel_converter.build_workbook(tables)
            excel_converter.save_workbook(workbook, output)

        logger.info(
            "files=%s cases=%s rows=%s output=%s dry_run=%s",
            len(tables),
            sum(len(table.rows) - 1 for table in tables),
            sum(len(table.rows) - 1 for table in tables),
            output,
            args.dry_run,
        )
    except (OSError, ValueError) as exc:
        logger.error("conversion_failed error=%s", exc)
        return 1
    finally:
        if workbook is not None:
            workbook.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
