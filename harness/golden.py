"""Golden case loader（ADR 0001 D7）。

支持两种 schema：
- golden.jsonl: 主 schema {id, category, raw_content, expected: {product_type, intent, ...}}
- option_golden.jsonl: 业务 QA schema（含 conversation 数组）—— M2 阶段在 LangFuse Annotation Queue
  做结构化标注后再用，M1 阶段不直接消费

按 category 索引以支持子集运行（如 harness run --category swap/place_order）。
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GoldenCase(BaseModel):
    """主 golden schema。"""

    model_config = ConfigDict(extra="allow")

    id: str
    category: str
    raw_content: str
    expected: dict[str, Any] = Field(default_factory=dict)
    quote_content: str | None = None
    notes: str | None = None


def load_golden(path: str | Path) -> list[GoldenCase]:
    """加载主 golden.jsonl（每行一条 JSON）。"""
    p = Path(path)
    if not p.exists():
        return []
    cases: list[GoldenCase] = []
    with p.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{p}:{lineno} invalid JSON: {e}") from e
            cases.append(GoldenCase.model_validate(obj))
    return cases


def index_by_category(cases: Iterable[GoldenCase]) -> dict[str, list[GoldenCase]]:
    """按 category 分组（子集运行用）。"""
    out: dict[str, list[GoldenCase]] = defaultdict(list)
    for c in cases:
        out[c.category].append(c)
    return dict(out)


def filter_by_category(
    cases: Iterable[GoldenCase], category_prefix: str | None
) -> list[GoldenCase]:
    """按 category 前缀过滤（如 'swap/' 命中 'swap/place_order' 等）。"""
    if not category_prefix:
        return list(cases)
    return [c for c in cases if c.category.startswith(category_prefix)]
