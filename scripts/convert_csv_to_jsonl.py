"""将 CSV 测试集还原为 JSONL。

用法：
    python scripts/convert_csv_to_jsonl.py
    python scripts/convert_csv_to_jsonl.py --input tests/datasets/biz/csv
    python scripts/convert_csv_to_jsonl.py --input example.csv --output-dir out

默认读取仓库 tests/datasets/biz/csv，输出到上级目录 tests/datasets/biz。
目录模式只扫描直接子级 CSV，按文件名排序；每个 CSV 还原为一个同名 JSONL。
单文件输入默认输出同目录同名 .jsonl，显式 --output-dir 优先。

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

try:
    import convert_jsonl_to_csv as forward
except ImportError:  # 以 scripts.convert_csv_to_jsonl 导入时
    from scripts import convert_jsonl_to_csv as forward

logger = logging.getLogger(__name__)
DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "tests" / "datasets" / "biz" / "csv"
DEFAULT_OUTPUT = DEFAULT_INPUT.parent  # tests/datasets/biz

# 逆向映射：CSV 列名 → JSONL 字段名（与 forward.CASE_COLUMNS / STEP_COLUMNS 对称）
CASE_FIELDS = {column: key for key, column in forward.CASE_COLUMNS.items()}
STEP_FIELDS = {column: key for key, column in forward.STEP_COLUMNS.items()}

BOOLEAN_COLUMNS = {"是否@机器人", "是否引用上一条"}
EXPECTED_COLUMNS = {"用例级预期", "步骤级预期"}
ASSERTION_COLUMNS = {"响应必须包含", "响应包含任一", "响应不得包含"}

reject_constant = forward.reject_constant

GOLDEN_HEADERS = (
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
GOLDEN_INQUIRY_HEADERS = (
    GOLDEN_HEADERS[:7] + ("引用说明", "用例级预期", "步骤级预期") + GOLDEN_HEADERS[7:]
)
GOLDEN_STEP_FIELDS = {
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


def parse_bool(value: str, location: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    raise ValueError(f"{location}: 布尔列必须是 true/false/null，实际={value!r}")


def parse_json_object(value: str, location: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value, parse_constant=reject_constant)
    except ValueError as exc:
        raise ValueError(f"{location}: 无效 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{location}: 必须是 JSON 对象")
    return parsed


def parse_text_or_json(value: str) -> Any:
    """字符串原样保留；JSON 数组/对象/null 还原为原值（与 forward.cell 对称）。"""
    stripped = value.lstrip()
    if stripped == "null":
        return None
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(value, parse_constant=reject_constant)
        except ValueError:
            return value
        return parsed
    return value


def find_inputs(source: Path) -> list[Path]:
    """目录只读直接子级 CSV（与 forward.find_inputs 对称）。"""
    if source.is_dir():
        paths = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == ".csv")
        if not paths:
            raise ValueError(f"目录中没有 CSV 文件: {source}")
        return paths
    if not source.is_file():
        raise ValueError(f"输入不存在或不是文件/目录: {source}")
    if source.suffix.lower() != ".csv":
        raise ValueError(f"输入文件必须为 .csv: {source}")
    return [source]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _step_number(row: dict[str, str], location: str) -> int:
    value = row.get("操作步骤序号", "")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{location}: 操作步骤序号 必须是正整数，实际={value!r}") from None
    if number < 1:
        raise ValueError(f"{location}: 操作步骤序号 必须是正整数，实际={value!r}")
    return number


def _decode_step(
    row: dict[str, str], text_key: str, path: Path, number: int
) -> dict[str, Any]:
    location = f"{path}: 记录 {number}"
    step: dict[str, Any] = {}
    text = row.get("测试数据", "")
    if not text.strip():
        raise ValueError(f"{location}: 测试数据 不能为空")
    step[text_key] = text
    for column, field in STEP_FIELDS.items():
        value = row.get(column, "")
        if value == "":
            continue
        cell_location = f"{location}, 列 {column}"
        if column in BOOLEAN_COLUMNS:
            step[field] = parse_bool(value, cell_location)
        elif column in EXPECTED_COLUMNS:
            step[field] = parse_json_object(value, cell_location)
        elif column in ASSERTION_COLUMNS:
            step[field] = parse_text_or_json(value)
        else:
            step[field] = value
    extra = row.get("步骤其他字段", "")
    if extra:
        step.update(parse_json_object(extra, f"{location}, 列 步骤其他字段"))
    return step


def _case_from_group(group: list[tuple[int, dict[str, str]]], path: Path) -> dict[str, Any]:
    first_number, first = group[0]
    case: dict[str, Any] = {}
    # 用例级字段（CASE_COLUMNS 逆映射）
    for column, field in CASE_FIELDS.items():
        value = first.get(column, "")
        if value:
            case[field] = value
    # 用例其他字段
    extra = first.get("用例其他字段", "")
    if extra:
        case.update(parse_json_object(extra, f"{path}: 记录 {first_number}, 列 用例其他字段"))
    # 结构判定：用例级预期非空 → conversation；否则 send_text + sub_scenes
    case_expected = first.get("用例级预期", "")
    if case_expected:
        case["expected"] = parse_json_object(
            case_expected, f"{path}: 记录 {first_number}, 列 用例级预期"
        )
        case["conversation"] = [
            _decode_step(row, "raw_content", path, number) for number, row in group
        ]
    else:
        case.update(_decode_step(first, "send_text", path, first_number))
        if len(group) > 1:
            case["sub_scenes"] = [
                _decode_step(row, "send_text", path, number) for number, row in group[1:]
            ]
    return case


def _read_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return next(csv.reader(stream), [])


def _golden_header(path: Path) -> tuple[str, ...] | None:
    header = _read_header(path)
    while header and not header[-1].strip():
        header.pop()
    trimmed = tuple(header)
    if trimmed in (GOLDEN_HEADERS, GOLDEN_INQUIRY_HEADERS):
        return trimmed
    return None


def _decode_golden_fields(row: dict[str, str], location: str) -> tuple[dict[str, Any], bool]:
    fields: dict[str, Any] = {}
    has_case_expected = False
    for column, field in GOLDEN_STEP_FIELDS.items():
        value = row.get(column)
        if value is None or value == "":
            continue
        cell_location = f"{location}, 列 {column}"
        if column in BOOLEAN_COLUMNS:
            fields[field] = parse_bool(value, cell_location)
        elif column in EXPECTED_COLUMNS:
            parsed = parse_json_object(value, cell_location)
            if "expected" in fields and fields["expected"] != parsed:
                raise ValueError(f"{cell_location}: 步骤级预期与用例级预期冲突")
            fields[field] = parsed
            has_case_expected |= column == "用例级预期"
        else:
            fields[field] = value
    return fields, has_case_expected


def load_golden_cases(path: Path) -> dict[str, list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[tuple[int, str, bool, dict[str, Any], str]]] = {}
    order: list[tuple[str, str]] = []
    for index, row in enumerate(read_rows(path), start=2):
        if not any((value or "").strip() for value in row.values()):
            continue
        location = f"{path}: 记录 {index}"
        filename = (row.get("来源文件") or "").strip()
        case_no = (row.get("用例编号") or "").strip()
        name = (row.get("用例名称") or "").strip()
        text = row.get("测试数据") or ""
        if not filename:
            raise ValueError(f"{location}: 来源文件 不能为空")
        if not case_no:
            raise ValueError(f"{location}: 用例编号 不能为空")
        if not name:
            raise ValueError(f"{location}: 用例名称 不能为空")
        if not text.strip():
            raise ValueError(f"{location}: 测试数据 不能为空")
        number = _step_number(row, location)
        fields, has_case_expected = _decode_golden_fields(row, location)
        key = (filename, case_no)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((number, name, has_case_expected, fields, location))
    outputs: dict[str, list[dict[str, Any]]] = {}
    for filename, case_no in order:
        steps = groups[(filename, case_no)]
        first_name = steps[0][1]
        for _, name, has_case_expected, _, location in steps:
            if name != first_name:
                raise ValueError(f"{location}, 列 用例名称: 用例 {case_no} 名称冲突")
            if len(steps) > 1 and has_case_expected:
                raise ValueError(f"{location}, 列 用例级预期: 多轮用例不支持用例级预期")
        ordered = sorted(steps, key=lambda item: item[0])
        for expected, (actual, *_) in enumerate(ordered, start=1):
            if actual != expected:
                raise ValueError(
                    f"{path}: 用例 {case_no} 操作步骤序号 必须从 1 连续递增，"
                    f"预期 {expected}，实际 {actual}"
                )
        case: dict[str, Any] = {"caseNo": case_no, "name": first_name}
        case.update(ordered[0][3])
        case["sub_scenes"] = [dict(step[3]) for step in ordered[1:]]
        case["category"] = Path(filename).stem.removeprefix("golden_")
        outputs.setdefault(filename, []).append(case)
    return outputs


def load_outputs(path: Path) -> dict[str, list[dict[str, Any]]]:
    if _golden_header(path) is not None:
        return load_golden_cases(path)
    _, cases = load_cases(path)
    return {f"{path.stem}.jsonl": cases}


def load_cases(path: Path) -> tuple[int, list[dict[str, Any]]]:
    """按 (来源文件, 源行号) 分组还原用例，保持首次出现顺序。"""
    groups: dict[tuple[str, str], list[tuple[int, dict[str, str]]]] = {}
    order: list[tuple[str, str]] = []
    for index, row in enumerate(read_rows(path), start=2):
        key = (row.get("来源文件", ""), row.get("源行号", ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((index, row))
    cases: list[dict[str, Any]] = []
    for key in order:
        # 每行只解析一次步骤序号，排序与连续性校验共用同一份结果。
        numbered = [
            (_step_number(row, f"{path}: 记录 {index}"), index, row) for index, row in groups[key]
        ]
        numbered.sort(key=lambda item: item[0])
        for expected, (actual, _, _) in enumerate(numbered, start=1):
            if actual != expected:
                raise ValueError(
                    f"{path}: 操作步骤序号 必须从 1 连续递增，预期 {expected}，实际 {actual}"
                )
        cases.append(_case_from_group([(index, row) for _, index, row in numbered], path))
    return len(cases), cases


def write_jsonl(output: Path, cases: list[dict[str, Any]]) -> None:
    """同目录临时文件写完关闭后替换，Windows 上同样不暴露半截输出。"""
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
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="CSV 文件或目录")
    parser.add_argument(
        "--output-dir", type=Path, help="默认：仓库 csv 目录 → biz/，其余目录 → 上级目录"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        source = args.input.resolve()
        paths = find_inputs(source)
        output_dir = (
            args.output_dir.resolve()
            if args.output_dir is not None
            else (DEFAULT_OUTPUT if source == DEFAULT_INPUT else source.parent)
        )
        # 整批先验证，后续文件有坏行时不修改任何 JSONL。
        prepared = [(path, load_outputs(path)) for path in paths]
        for path, outputs in prepared:
            for filename, cases in outputs.items():
                target = output_dir / filename
                write_jsonl(target, cases)
                logger.info(
                    "input=%s cases=%s output=%s",
                    path,
                    len(cases),
                    target,
                )
        logger.info(
            "files=%s cases=%s",
            len(prepared),
            sum(len(cases) for _, outputs in prepared for cases in outputs.values()),
        )
    except (OSError, ValueError) as exc:
        logger.error("conversion_failed error=%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
