#!/usr/bin/env python3
"""Convert YAML regression cases to UTF-8 JSONL without changing case data."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys at every level."""


def construct_unique_mapping(
    loader: UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicated = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicated:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key ({key!r})",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


def validate_case(case: dict[str, Any], *, source: Path, index: int) -> None:
    location = f"{source} 第 {index} 条用例"
    try:
        json.dumps(case, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{location} 包含无法写入 JSON 的值: {exc}") from exc


def load_yaml_cases(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"输入文件不存在: {path}")
    if path.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError(f"输入文件必须是 .yaml 或 .yml: {path}")
    loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeySafeLoader)
    if isinstance(loaded, dict):
        loaded = [loaded]
    if not isinstance(loaded, list):
        raise ValueError(f"YAML 顶层必须是用例数组或单个用例对象: {path}")
    cases: list[dict[str, Any]] = []
    for index, case in enumerate(loaded, 1):
        if not isinstance(case, dict):
            raise ValueError(f"{path} 第 {index} 条用例不是对象")
        validate_case(case, source=path, index=index)
        cases.append(case)
    return cases


def load_all_cases(paths: Sequence[Path]) -> list[dict[str, Any]]:
    all_cases: list[dict[str, Any]] = []
    seen_case_nos: dict[str, str] = {}
    for path in paths:
        for index, case in enumerate(load_yaml_cases(path), 1):
            case_no = case.get("caseNo")
            if isinstance(case_no, str) and case_no:
                previous = seen_case_nos.get(case_no)
                if previous:
                    raise ValueError(
                        f"caseNo 重复: {case_no}，分别位于 {previous} 和 {path} 第 {index} 条"
                    )
                seen_case_nos[case_no] = f"{path} 第 {index} 条"
            all_cases.append(case)
    if not all_cases:
        raise ValueError("输入 YAML 中没有用例")
    return all_cases


def encode_jsonl(cases: Sequence[dict[str, Any]]) -> str:
    lines = [
        json.dumps(case, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        for case in cases
    ]
    return "\n".join(lines) + "\n"


def infer_output(inputs: Sequence[Path], output: Path | None) -> Path:
    if output is not None:
        return output
    if len(inputs) != 1:
        raise ValueError("指定多个输入文件时必须同时指定 --output")
    return inputs[0].with_suffix(".jsonl")


def write_atomic(output: Path, content: str, *, force: bool) -> None:
    if output.exists() and not force:
        raise ValueError(f"输出文件已存在: {output}；确认覆盖请添加 --force")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, output)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def run_self_test() -> int:
    source_cases = [
        {
            "name": "示例用例",
            "caseNo": "case-1",
            "send_text": "第一行\n第二行",
            "response_contains": "中文内容\n保持换行",
            "sub_scenes": [{"send_text": "确认下单", "response_contains": "成功"}],
        }
    ]
    encoded = encode_jsonl(source_cases)
    decoded = [json.loads(line) for line in encoded.splitlines() if line]
    with tempfile.TemporaryDirectory() as temp_dir:
        duplicate_yaml = Path(temp_dir) / "duplicate.yaml"
        duplicate_yaml.write_text(
            "- name: 第一名称\n  name: 第二名称\n  send_text: 测试\n",
            encoding="utf-8",
        )
        try:
            load_yaml_cases(duplicate_yaml)
            duplicate_key_blocked = False
        except yaml.YAMLError:
            duplicate_key_blocked = True
    checks = [
        ("一条用例对应一行", len(decoded) == 1),
        ("字段和值完整保留", decoded == source_cases),
        ("中文不转义", "示例用例" in encoded and "\\u793a" not in encoded),
        ("拒绝重复 YAML 字段", duplicate_key_blocked),
    ]
    for label, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {label}")
    passed_count = sum(passed for _, passed in checks)
    print(f"自检结果：{passed_count}/{len(checks)}")
    return 0 if passed_count == len(checks) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将 YAML 自动化测试用例转换为一行一条的 JSONL"
    )
    parser.add_argument(
        "inputs", nargs="*", type=Path, help="一个或多个 YAML 文件；按参数顺序合并"
    )
    parser.add_argument("-o", "--output", type=Path, help="输出 JSONL 路径")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有输出文件")
    parser.add_argument("--check-only", action="store_true", help="只校验，不生成 JSONL")
    parser.add_argument("--self-test", action="store_true", help="运行离线自检后退出")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            return run_self_test()
        if not args.inputs:
            raise ValueError("请至少指定一个 YAML 输入文件")
        cases = load_all_cases(args.inputs)
        encoded = encode_jsonl(cases)
        print(f"校验通过：输入 {len(args.inputs)} 个 YAML，共 {len(cases)} 条用例")
        if args.check_only:
            print("仅校验模式：未生成 JSONL")
            return 0
        output = infer_output(args.inputs, args.output)
        if output.suffix.lower() != ".jsonl":
            raise ValueError(f"输出文件必须使用 .jsonl 后缀: {output}")
        write_atomic(output, encoded, force=args.force)
        print(f"转换完成：{output}（{len(cases)} 行）")
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
