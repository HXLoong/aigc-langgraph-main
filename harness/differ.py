"""Differ — 字段级 `==` diff（ADR 0001 D7 修订版）。

按 expected 字段递归比对（actual 多出的字段不报告）。
diff 路径格式：`params.price_type` 这种点分路径，比 unified diff 对 AI 工具更友好。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class FieldDiff(BaseModel):
    """单字段差异。"""

    model_config = ConfigDict(extra="allow")

    path: str
    expected: Any = None
    actual: Any = None


def diff_fields(
    expected: dict[str, Any] | None,
    actual: dict[str, Any] | None,
    prefix: str = "",
) -> list[FieldDiff]:
    """递归对比 expected vs actual 中 expected 涵盖的字段。

    - 只检查 expected 中出现的 key（actual 多出的字段视为无关）
    - dict 嵌套递归
    - list 仅比较长度 + 逐项（list 内嵌 dict 仍递归）
    - 标量用 ==
    """
    if expected is None:
        return []

    diffs: list[FieldDiff] = []
    actual = actual or {}

    for key, e_val in expected.items():
        path = f"{prefix}.{key}" if prefix else key
        a_val = actual.get(key)

        if isinstance(e_val, dict) and isinstance(a_val, dict):
            diffs.extend(diff_fields(e_val, a_val, prefix=path))
            continue

        if isinstance(e_val, list) and isinstance(a_val, list):
            if len(e_val) != len(a_val):
                diffs.append(
                    FieldDiff(
                        path=f"{path}.length",
                        expected=len(e_val),
                        actual=len(a_val),
                    )
                )
            for i, (e_item, a_item) in enumerate(zip(e_val, a_val, strict=False)):
                item_path = f"{path}[{i}]"
                if isinstance(e_item, dict) and isinstance(a_item, dict):
                    diffs.extend(diff_fields(e_item, a_item, prefix=item_path))
                elif e_item != a_item:
                    diffs.append(FieldDiff(path=item_path, expected=e_item, actual=a_item))
            continue

        if e_val != a_val:
            diffs.append(FieldDiff(path=path, expected=e_val, actual=a_val))

    return diffs


def is_pass(diffs: list[FieldDiff]) -> bool:
    """没有差异即 PASS。"""
    return len(diffs) == 0
