"""JSONL 导出的 CLI 契约及真实测试集回读验证。"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "convert_jsonl_to_csv.py"
FIXTURES = ROOT / "tests" / "fixtures" / "biz"


def run_cli(*args: str | Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=cwd or ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def write_cases(path: Path, cases: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_single_step_preserves_text_types_and_unknown_fields(tmp_path: Path) -> None:
    source = tmp_path / "中文.jsonl"
    case = {
        "id": "001",
        "caseNo": "external-2",
        "name": "用例名",
        "category": "option/inquiry",
        "type": "positive",
        "source": "json/golden_case_raw/普通询价",
        "scene": "首次询价",
        "send_text": '  中文,"报价"\n下一行  ',
        "at_bot": False,
        "quote_previous": None,
        "quote_desc": "引用报价结果",
        "expected": {"intent": "new_inquiry"},
        "response_contains": ["费率", "下一步"],
        "response_contains_any": "A\nB",
        "response_not_contains": None,
        "precondition": "已登录",
        "custom": [0, False],
    }
    # BOM 和空白行不影响物理来源行号。
    source.write_text("\n" + json.dumps(case, ensure_ascii=False) + "\n\n", encoding="utf-8-sig")
    result = run_cli("--input", source, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    rows = read_rows(tmp_path / "csv" / "中文.csv")
    assert len(rows) == 1
    row = rows[0]
    assert [row[k] for k in ("来源文件", "源行号", "用例ID", "用例编号", "用例名称")] == [
        "中文.jsonl",
        "2",
        "001",
        "external-2",
        "用例名",
    ]
    assert row["需求场景"] == "普通询价"
    assert row["步骤场景"] == "首次询价"
    assert row["测试数据"] == case["send_text"]
    assert row["是否@机器人"] == "false"
    assert row["是否引用上一条"] == "null"
    assert row["引用说明"] == "引用报价结果"
    assert row["用例级预期"] == ""
    assert json.loads(row["步骤级预期"]) == case["expected"]
    assert json.loads(row["响应必须包含"]) == case["response_contains"]
    assert row["响应包含任一"] == "A\nB"
    assert row["响应不得包含"] == "null"
    assert json.loads(row["用例其他字段"]) == {"precondition": "已登录", "custom": [0, False]}
    assert row["步骤其他字段"] == ""


def test_scenes_do_not_inherit_assertions_or_flags(tmp_path: Path) -> None:
    source = tmp_path / "scenes.jsonl"
    write_cases(
        source,
        [
            {
                "id": "same",
                "send_text": "询价",
                "at_bot": True,
                "expected": {"intent": "inquiry"},
                "response_contains": ["报价"],
                "sub_scenes": [
                    {
                        "send_text": "补参",
                        "scene": "第二步",
                        "quote_previous": False,
                        "expected": {"intent": "place"},
                        "response_not_contains": "缺参",
                        "extra": 7,
                    },
                    {"send_text": "确认"},
                ],
            },
            {"id": "same", "send_text": "独立用例"},
        ],
    )
    result = run_cli("--input", source)
    assert result.returncode == 0, result.stderr
    rows = read_rows(tmp_path / "csv" / "scenes.csv")
    assert [r["操作步骤序号"] for r in rows] == ["1", "2", "3", "1"]
    assert [r["测试数据"] for r in rows] == ["询价", "补参", "确认", "独立用例"]
    assert all(r["用例ID"] == "same" for r in rows)
    assert all(r["用例编号"] == "" for r in rows)
    assert rows[1]["响应必须包含"] == rows[1]["是否@机器人"] == ""
    assert rows[1]["是否引用上一条"] == "false"
    assert json.loads(rows[1]["步骤级预期"]) == {"intent": "place"}
    assert json.loads(rows[1]["步骤其他字段"]) == {"extra": 7}
    assert rows[2]["步骤级预期"] == rows[2]["响应不得包含"] == ""


def test_conversation_preserves_summary_without_inventing_steps(tmp_path: Path) -> None:
    source = tmp_path / "conversation.jsonl"
    summary = {"output": "[第1轮] 报价\n[第2轮] 等待成交通知"}
    write_cases(
        source,
        [
            {
                "id": "c",
                "source": "other/source",
                "expected": summary,
                "scene": "用例范围说明",
                "response_contains": "用例范围断言",
                "conversation": [
                    {
                        "raw_content": "下单",
                        "quote_desc": "引用上一条",
                        "expected": {"intent": "place"},
                        "custom": None,
                    }
                ],
            }
        ],
    )
    result = run_cli("--input", source)
    assert result.returncode == 0, result.stderr
    rows = read_rows(tmp_path / "csv" / "conversation.csv")
    assert len(rows) == 1
    row = rows[0]
    assert json.loads(row["用例级预期"]) == summary
    assert json.loads(row["步骤级预期"]) == {"intent": "place"}
    assert row["是否引用上一条"] == row["需求场景"] == row["步骤场景"] == ""
    assert row["响应必须包含"] == ""
    assert json.loads(row["用例其他字段"]) == {
        "scene": "用例范围说明",
        "response_contains": "用例范围断言",
    }
    assert json.loads(row["步骤其他字段"]) == {"custom": None}


def test_directory_output_overwrite_and_dry_run(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "nested").mkdir()
    write_cases(inputs / "b.jsonl", [{"send_text": "B"}])
    write_cases(inputs / "a.jsonl", [{"send_text": "A"}])
    write_cases(inputs / "nested" / "ignored.jsonl", [{"send_text": "ignored"}])
    output = tmp_path / "output"
    result = run_cli("--input", inputs, "--output-dir", output, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert not output.exists()
    assert result.stderr.index("a.jsonl") < result.stderr.index("b.jsonl")
    result = run_cli("--input", inputs, "--output-dir", output)
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in output.iterdir()) == ["a.csv", "b.csv"]
    write_cases(inputs / "a.jsonl", [{"send_text": "新数据"}])
    result = run_cli("--input", inputs, "--output-dir", output)
    assert result.returncode == 0, result.stderr
    assert [r["测试数据"] for r in read_rows(output / "a.csv")] == ["新数据"]
    assert json.loads((inputs / "b.jsonl").read_text(encoding="utf-8"))["send_text"] == "B"


@pytest.mark.parametrize(
    "invalid",
    [
        "{broken",
        "[]",
        "{}",
        '{"conversation": []}',
        '{"conversation": [{"raw_content": "x"}], "send_text": "y"}',
        '{"conversation": [1]}',
        '{"send_text": "x", "sub_scenes": {}}',
        '{"send_text": "x", "sub_scenes": [{}]}',
        '{"send_text": 3}',
        '{"send_text": "x", "raw_content": "y"}',
        '{"send_text": "x", "sub_scenes": [{"send_text": "y", "sub_scenes": []}]}',
    ],
)
def test_invalid_batch_does_not_write_partial_outputs(tmp_path: Path, invalid: str) -> None:
    write_cases(tmp_path / "a.jsonl", [{"send_text": "有效"}])
    (tmp_path / "b.jsonl").write_text("\n" + invalid + "\n", encoding="utf-8")
    result = run_cli("--input", tmp_path)
    assert result.returncode != 0
    assert "b.jsonl:2" in result.stderr
    assert not (tmp_path / "csv").exists()


def test_missing_and_empty_input_directories_report_failure(tmp_path: Path) -> None:
    for source, message in (
        (tmp_path / "missing.jsonl", "输入不存在"),
        (tmp_path, "目录中没有 JSONL 文件"),
    ):
        result = run_cli("--input", source)
        assert result.returncode != 0
        assert message in result.stderr
        assert not (tmp_path / "csv").exists()


def test_real_categories_and_default_input_from_another_directory(tmp_path: Path) -> None:
    result = run_cli("--output-dir", tmp_path / "csv", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    sources = sorted(FIXTURES.glob("*.jsonl"))
    assert sources
    assert sorted(p.stem for p in (tmp_path / "csv").glob("*.csv")) == [p.stem for p in sources]
    for source in sources:
        rows = read_rows(tmp_path / "csv" / f"{source.stem}.csv")
        originals = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
        expected_inputs = []
        expected_ids = []
        expected_numbers = []
        expected_summaries = []
        expected_steps = []
        for case in originals:
            if "conversation" in case:
                steps = case["conversation"]
                expected_inputs.extend(t["raw_content"] for t in steps)
                summary = case.get("expected")
            else:
                steps = [case, *case.get("sub_scenes", [])]
                expected_inputs.extend(t["send_text"] for t in steps)
                summary = None
            expected_ids.extend([case.get("id", "")] * len(steps))
            expected_numbers.extend(str(i) for i in range(1, len(steps) + 1))
            expected_summaries.extend([summary] * len(steps))
            expected_steps.extend(steps)
        assert [r["测试数据"] for r in rows] == expected_inputs
        assert [r["用例ID"] for r in rows] == expected_ids
        assert [r["操作步骤序号"] for r in rows] == expected_numbers
        assert [json.loads(r["用例级预期"]) if r["用例级预期"] else None for r in rows] == (
            expected_summaries
        )
        for row, step in zip(rows, expected_steps, strict=True):
            for key, column in (
                ("expected", "步骤级预期"),
                ("response_contains", "响应必须包含"),
                ("response_contains_any", "响应包含任一"),
                ("response_not_contains", "响应不得包含"),
            ):
                if key not in step:
                    assert row[column] == ""
                elif isinstance(step[key], str):
                    assert row[column] == step[key]
                else:
                    assert json.loads(row[column]) == step[key]
