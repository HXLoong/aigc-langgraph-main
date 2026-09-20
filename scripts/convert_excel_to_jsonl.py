"""按黄金数据集 Excel 的严格表头导入 JSONL（期权、互换共用）。

用法：
    python scripts/convert_excel_to_jsonl.py --input 黄金数据集.xlsx
    python scripts/convert_excel_to_jsonl.py --input 黄金数据集.xlsx --output-dir out
    python scripts/convert_excel_to_jsonl.py --input 黄金数据集.xlsx --dry-run

支持 10 列通用表、13 列询价表，列名和顺序必须与 HEADERS / INQUIRY_HEADERS
完全一致。只读 Excel，不读取已有 JSONL。按来源文件和用例编号聚合，步骤从 1
连续编号；根对象为第一步，其余放入 sub_scenes。每个用例仅占一条物理行。

三个响应断言列始终保留原文（含 JSON 文本），步骤级预期必须是 JSON 对象。
空布尔字段省略：现有 harness 默认首轮 at_bot=True，后续 False；未指定引用时
由 runner 决定，导入器不推导引用关系。用例级预期只支持单轮，避免改变评估语义。

默认输出到输入文件旁的 <文件名>_jsonl/，每个来源文件输出一个同名 JSONL。
整批校验后逐文件临时写入并替换，重复运行覆盖同名输出。dry-run 不写任何文件。
文件名不允许路径或 Windows 保留名称；报错包含工作表、Excel 行号和列名。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

logger = logging.getLogger(__name__)
HEADERS = (
    "来源文件",
    "用例编号",
    "用例名称",
    "操作步骤序号",
    "测试数据",
    "是否@机器人",
    "是否引用上一条",
    "响应必须包含",
    "响应包含任一",
    "响应不得包含",
)
INQUIRY_HEADERS = HEADERS[:7] + ("引用说明", "用例级预期", "步骤级预期") + HEADERS[7:]
STEP_FIELDS = {
    "测试数据": "send_text",
    "是否@机器人": "at_bot",
    "是否引用上一条": "quote_previous",
    "引用说明": "quote_desc",
    "用例级预期": "expected",
    "步骤级预期": "expected",
    "响应必须包含": "response_contains",
    "响应包含任一": "response_contains_any",
    "响应不得包含": "response_not_contains",
}
BOOLEAN_COLUMNS = {"是否@机器人", "是否引用上一条"}
EXPECTED_COLUMNS = {"用例级预期", "步骤级预期"}
ASSERTION_COLUMNS = {"响应必须包含", "响应包含任一", "响应不得包含"}


@dataclass
class InputStep:
    location: str
    filename: str
    case_no: str
    name: str
    number: int
    fields: dict[str, Any]
    has_case_expected: bool


def text_value(value: Any, location: str, *, required: bool = False) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{location}: 必须是{'非空' if required else ''}文本")
    return value


def source_filename(value: Any, location: str) -> str:
    name = text_value(value, location, required=True)
    if (
        re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        or name != name.strip()
        or name.endswith((".", " "))
        or PureWindowsPath(name).is_reserved()
        or not name.lower().endswith(".jsonl")
        or not name[:-6].strip(". ")
    ):
        raise ValueError(f"{location}: 必须是安全的 .jsonl 文件名（不得包含路径或保留名称）")
    return name


def step_number(value: Any, location: str) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        value = int(value)
    if type(value) is not int or value < 1:
        raise ValueError(f"{location}: 必须是从 1 开始的正整数")
    return value


def boolean_value(value: Any, location: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{location}: 必须是 Excel 布尔值或 true/false 文本")


def reject_constant(value: str) -> None:
    raise ValueError(f"不支持非标准 JSON 常量 {value}")


def expected_object(value: Any, location: str) -> dict[str, Any]:
    text = text_value(value, location, required=True)
    try:
        parsed = json.loads(text, parse_constant=reject_constant)
        # JSON 的 1e999 会被 Python 解析为 inf；必须在整批校验时拒绝。
        json.dumps(parsed, allow_nan=False)
    except ValueError as exc:
        raise ValueError(f"{location}: 无效 JSON 预期: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{location}: 预期必须是 JSON 对象")
    return parsed


def parse_row(headers: tuple[str, ...], values: list[Any], location: str) -> InputStep:
    row = dict(zip(headers, values, strict=True))
    filename = source_filename(row["来源文件"], f"{location}, 列 来源文件")
    case_no = text_value(row["用例编号"], f"{location}, 列 用例编号", required=True)
    name = text_value(row["用例名称"], f"{location}, 列 用例名称", required=True)
    number = step_number(row["操作步骤序号"], f"{location}, 列 操作步骤序号")
    text_value(row["测试数据"], f"{location}, 列 测试数据", required=True)
    fields: dict[str, Any] = {}
    has_case_expected = False
    for header in headers:
        value = row[header]
        if header not in STEP_FIELDS or value is None or value == "":
            continue
        cell_location = f"{location}, 列 {header}"
        key = STEP_FIELDS[header]
        if header in BOOLEAN_COLUMNS:
            fields[key] = boolean_value(value, cell_location)
        elif header in EXPECTED_COLUMNS:
            parsed = expected_object(value, cell_location)
            if "expected" in fields and fields["expected"] != parsed:
                raise ValueError(f"{cell_location}: 步骤级预期与用例级预期冲突")
            fields[key] = parsed
            has_case_expected |= header == "用例级预期"
        else:
            fields[key] = text_value(value, cell_location)
            if header in ASSERTION_COLUMNS and value.lstrip().startswith(("{", "[")):
                logger.warning(
                    "literal_assertion location=%s 内容疑似 JSON，按文本断言原样保留，不拆分预期",
                    cell_location,
                )
    return InputStep(location, filename, case_no, name, number, fields, has_case_expected)


def load_cases(source: Path) -> dict[str, list[dict[str, Any]]]:
    """整批读取并校验，返回保持文件/用例首次出现顺序的输出。"""
    if source.suffix.lower() != ".xlsx" or not source.is_file():
        raise ValueError(f"输入必须是存在的 .xlsx 文件: {source}")
    groups: dict[tuple[str, str], list[InputStep]] = {}
    filenames: dict[str, str] = {}
    workbook = load_workbook(source, read_only=True, data_only=False)
    try:
        for sheet in workbook:
            rows = (
                (number, cells)
                for number, cells in enumerate(sheet.iter_rows(), 1)
                if any(cell.value is not None for cell in cells)
            )
            first_row = next(rows, None)
            if first_row is None:
                continue
            header_number, header_cells = first_row
            headers = tuple(cell.value for cell in header_cells)
            if header_number != 1 or headers not in (HEADERS, INQUIRY_HEADERS):
                raise ValueError(
                    f"{source}: 工作表 {sheet.title!r}, 行 {header_number}, 列 表头: "
                    f"表头及顺序必须严格一致；实际={headers!r}；"
                    f"预期通用表头={HEADERS!r}；预期询价表头={INQUIRY_HEADERS!r}"
                )
            for row_number, cells in rows:
                location = f"{source}: 工作表 {sheet.title!r}, 行 {row_number}"
                for header, cell in zip(headers, cells, strict=True):
                    if cell.data_type in {"f", "e"}:
                        raise ValueError(f"{location}, 列 {header}: 不支持公式或 Excel 错误单元格")
                step = parse_row(headers, [cell.value for cell in cells], location)
                previous = filenames.setdefault(step.filename.casefold(), step.filename)
                if previous != step.filename:
                    raise ValueError(f"{location}, 列 来源文件: 文件名大小写冲突: {previous}")
                groups.setdefault((step.filename, step.case_no), []).append(step)
    finally:
        workbook.close()
    if not groups:
        raise ValueError(f"{source}: 没有可转换的用例")

    outputs: dict[str, list[dict[str, Any]]] = {}
    for (filename, case_no), steps in groups.items():
        first = steps[0]
        for step in steps:
            if step.name != first.name:
                raise ValueError(f"{step.location}, 列 用例名称: 用例 {case_no} 名称冲突")
            if len(steps) > 1 and step.has_case_expected:
                raise ValueError(f"{step.location}, 列 用例级预期: 多轮用例不支持用例级预期")
        ordered = sorted(steps, key=lambda step: step.number)
        for number, step in enumerate(ordered, 1):
            if step.number != number:
                raise ValueError(
                    f"{step.location}, 列 操作步骤序号: 用例 {case_no} 必须从 1 连续递增，"
                    f"存在重复或缺失；预期 {number}，实际 {step.number}"
                )
        case = {"caseNo": case_no, "name": first.name, **ordered[0].fields}
        case["sub_scenes"] = [step.fields for step in ordered[1:]]
        case["category"] = Path(filename).stem.removeprefix("golden_")
        outputs.setdefault(filename, []).append(case)
    return outputs


def write_jsonl(output: Path, cases: list[dict[str, Any]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            for case in cases:
                stream.write(json.dumps(case, ensure_ascii=False, allow_nan=False) + "\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", type=Path, required=True, help="输入 .xlsx 文件")
    parser.add_argument("--output-dir", type=Path, help="默认：输入文件旁的 <文件名>_jsonl 目录")
    parser.add_argument("--dry-run", action="store_true", help="仅校验并统计，不写文件")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        source = args.input.resolve()
        output_dir = (
            args.output_dir.resolve()
            if args.output_dir is not None
            else source.parent / f"{source.stem}_jsonl"
        )
        outputs = load_cases(source)
        total_steps = 0
        for filename, cases in outputs.items():
            output = output_dir / filename
            steps = sum(1 + len(case["sub_scenes"]) for case in cases)
            total_steps += steps
            if not args.dry_run:
                write_jsonl(output, cases)
            logger.info(
                "output=%s cases=%s steps=%s dry_run=%s",
                output,
                len(cases),
                steps,
                args.dry_run,
            )
        logger.info(
            "files=%s cases=%s steps=%s dry_run=%s",
            len(outputs),
            sum(map(len, outputs.values())),
            total_steps,
            args.dry_run,
        )
    except (OSError, ValueError, BadZipFile, InvalidFileException, ParseError) as exc:
        logger.error("conversion_failed error=%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
