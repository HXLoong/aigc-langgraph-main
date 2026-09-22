"""Excel 导入的严格表头、多轮聚合和原文保留契约。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "convert_excel_to_jsonl.py"
HEADERS = [
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
]
INQUIRY_HEADERS = HEADERS[:7] + ["引用说明", "用例级预期", "步骤级预期"] + HEADERS[7:]


def run_cli(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def write_book(path: Path, sheets: list[tuple[str, list[str], list[list[Any]]]]) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, headers, rows in sheets:
        sheet = workbook.create_sheet(title)
        if headers:
            sheet.append(headers)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    workbook.close()


def step(number: Any = 1, **changes: Any) -> list[Any]:
    values = dict(
        zip(
            HEADERS,
            [
                "golden_option_open_case.jsonl",
                "case-001",
                "多轮开仓",
                number,
                "  中文输入\n下一行  ",
                "true",
                None,
                "预期\n原文  ",
                None,
                None,
            ],
            strict=True,
        )
    )
    values.update(changes)
    return [values[h] for h in HEADERS]


def test_multiturn_one_physical_line_in_header_order_and_independent_assertions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "黄金.xlsx"
    write_book(
        source,
        [
            (
                "期权",
                HEADERS,
                [
                    step(
                        "2",
                        测试数据="确认",
                        是否引用上一条=True,
                        **{"是否@机器人": False, "响应必须包含": None},
                    ),
                    step("1"),
                ],
            ),
            ("互换", HEADERS, [step(来源文件="swap_prod_data.jsonl", 用例编号="swap-001")]),
            ("空表", [], []),
        ],
    )
    result = run_cli("--input", source)
    assert result.returncode == 0, result.stderr
    output = tmp_path / "黄金_jsonl"
    raw = (output / "golden_option_open_case.jsonl").read_text(encoding="utf-8")
    assert len(raw.splitlines()) == 1
    obj = json.loads(raw)
    assert list(obj) == [
        "caseNo",
        "name",
        "send_text",
        "at_bot",
        "response_contains",
        "sub_scenes",
        "category",
    ]
    assert obj["send_text"] == "  中文输入\n下一行  "
    assert obj["response_contains"] == "预期\n原文  "
    assert obj["category"] == "option_open_case"
    assert obj["sub_scenes"] == [{"send_text": "确认", "at_bot": False, "quote_previous": True}]
    assert (output / "swap_prod_data.jsonl").is_file()
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert run_cli("--input", source).returncode == 0
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_inquiry_expected_and_literal_json_assertions(tmp_path: Path) -> None:
    source = tmp_path / "input.xlsx"
    literal = '{"product_type": "option_close", "output": "整段预期"}'
    row = step(来源文件="golden_option_inquiry_case.jsonl")
    row = (
        row[:7]
        + ["原文引用", '{"intent":"new_inquiry"}', '{"intent":"new_inquiry"}']
        + [literal, "A\nB", "错误"]
    )
    write_book(source, [("询价", INQUIRY_HEADERS, [row])])
    result = run_cli("--input", source)
    assert result.returncode == 0, result.stderr
    obj = json.loads((tmp_path / "input_jsonl/golden_option_inquiry_case.jsonl").read_text("utf-8"))
    assert obj["expected"] == {"intent": "new_inquiry"}
    assert obj["quote_desc"] == "原文引用"
    assert obj["response_contains"] == literal
    assert list(obj).index("expected") < list(obj).index("response_contains")
    assert (
        "WARNING" in result.stderr and "询价" in result.stderr and "响应必须包含" in result.stderr
    )


@pytest.mark.parametrize("headers", [HEADERS[::-1], HEADERS[:-1], HEADERS + ["额外列"]])
def test_strict_headers(tmp_path: Path, headers: list[str]) -> None:
    source = tmp_path / "input.xlsx"
    write_book(source, [("坏表头", headers, [])])
    result = run_cli("--input", source)
    assert result.returncode == 1
    assert "坏表头" in result.stderr and "表头" in result.stderr and "来源文件" in result.stderr
    assert not (tmp_path / "input_jsonl").exists()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("来源文件", "../escape.jsonl"),
        ("来源文件", "C:\\escape.jsonl"),
        ("来源文件", "CON.jsonl"),
        ("来源文件", "bad.txt"),
        ("用例编号", None),
        ("用例名称", None),
        ("测试数据", " "),
        ("测试数据", 100),
        ("测试数据", "=1+1"),
        ("是否@机器人", "yes"),
        ("是否引用上一条", 1),
        ("操作步骤序号", 0),
        ("操作步骤序号", 1.5),
        ("操作步骤序号", True),
        ("响应必须包含", 42),
    ],
)
def test_invalid_cells_report_location_without_writes(
    tmp_path: Path,
    column: str,
    value: Any,
) -> None:
    source = tmp_path / "input.xlsx"
    write_book(source, [("错误定位", HEADERS, [step(**{column: value})])])
    result = run_cli("--input", source)
    assert result.returncode == 1
    assert "错误定位" in result.stderr and "2" in result.stderr and column in result.stderr
    assert not (tmp_path / "input_jsonl").exists()


@pytest.mark.parametrize(
    "rows",
    [
        [step(1), step(1)],
        [step(1), step(3)],
        [step(2)],
        [step(1), step(2, 用例名称="不一致")],
    ],
)
def test_invalid_groups_do_not_overwrite_any_output(tmp_path: Path, rows: list[list[Any]]) -> None:
    source = tmp_path / "input.xlsx"
    output = tmp_path / "existing"
    output.mkdir()
    target = output / "swap_prod_data.jsonl"
    target.write_text("untouched\n", encoding="utf-8")
    write_book(
        source,
        [
            ("有效", HEADERS, [step(来源文件=target.name)]),
            ("无效", HEADERS, rows),
        ],
    )
    result = run_cli("--input", source, "--output-dir", output)
    assert result.returncode == 1
    assert "无效" in result.stderr
    assert list(output.iterdir()) == [target]
    assert target.read_text("utf-8") == "untouched\n"


@pytest.mark.parametrize(
    ("case_expected", "step_expected", "multiturn"),
    [
        ('{"intent":"a"}', '{"intent":"b"}', False),
        ('{"intent":"a"}', None, True),
        (None, "[]", False),
        (None, "broken", False),
        (None, '{"value": NaN}', False),
    ],
)
def test_invalid_expectations(
    tmp_path: Path,
    case_expected: str | None,
    step_expected: str | None,
    multiturn: bool,
) -> None:
    source = tmp_path / "input.xlsx"
    row = step()
    rows = [row[:7] + [None, case_expected, step_expected] + row[7:]]
    if multiturn:
        row = step(2)
        rows.append(row[:7] + [None, None, None] + row[7:])
    write_book(source, [("预期校验", INQUIRY_HEADERS, rows)])
    result = run_cli("--input", source)
    assert result.returncode == 1
    assert "预期校验" in result.stderr and "预期" in result.stderr


def test_dry_run_group_order_and_loader_compatibility(tmp_path: Path) -> None:
    from harness.golden import load_golden
    from scripts.check_fixture_consistency import validate

    source = tmp_path / "input.xlsx"
    output = tmp_path / "fixtures/categories"
    write_book(
        source,
        [
            (
                "期权平仓",
                HEADERS,
                [
                    step(2, 用例编号="case-b", **{"是否@机器人": None, "响应必须包含": None}),
                    step(1, 用例编号="case-a"),
                    step(1, 用例编号="case-b"),
                ],
            )
        ],
    )
    result = run_cli("--input", source, "--output-dir", output, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "cases=2" in result.stderr and "steps=3" in result.stderr
    assert not output.exists()
    assert run_cli("--input", source, "--output-dir", output).returncode == 0
    cases = load_golden(output)
    assert [c.id for c in cases] == ["case-b", "case-a"]
    assert len(cases[0].turns) == 2
    assert validate(output) == []


def test_overflow_expected_fails_during_validation_before_any_write(tmp_path: Path) -> None:
    source = tmp_path / "input.xlsx"
    row = step()
    write_book(
        source,
        [
            ("有效", HEADERS, [step(来源文件="swap_prod_data.jsonl")]),
            (
                "溢出预期",
                INQUIRY_HEADERS,
                [
                    row[:7] + [None, None, '{"rate":1e999}'] + row[7:],
                ],
            ),
        ],
    )
    result = run_cli("--input", source)
    assert result.returncode == 1
    assert "溢出预期" in result.stderr and "步骤级预期" in result.stderr
    assert not (tmp_path / "input_jsonl").exists()


def test_aggregate_across_sheets_and_case_expected_fallback(tmp_path: Path) -> None:
    source = tmp_path / "input.xlsx"
    single = step(来源文件="golden_option_inquiry_case.jsonl", 用例编号="inquiry")
    write_book(
        source,
        [
            ("前半", HEADERS, [step(1)]),
            ("后半", HEADERS, [step(2)]),
            (
                "单轮预期",
                INQUIRY_HEADERS,
                [
                    single[:7] + [None, '{"intent":"new_inquiry"}', None] + single[7:],
                ],
            ),
        ],
    )
    result = run_cli("--input", source)
    assert result.returncode == 0, result.stderr
    output = tmp_path / "input_jsonl"
    assert (
        len(json.loads((output / "golden_option_open_case.jsonl").read_text("utf-8"))["sub_scenes"])
        == 1
    )
    assert json.loads((output / "golden_option_inquiry_case.jsonl").read_text("utf-8"))[
        "expected"
    ] == {
        "intent": "new_inquiry",
    }
