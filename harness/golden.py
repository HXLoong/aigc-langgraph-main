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
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: case 来源（grill-with-docs 2026-05-10 第 4 决策）
#: - business_seed: 业务方手写种子（高质量基线，PASS 阈值 ≥ 90%）
#: - llm_paraphrase: LLM 对抗式 paraphrase（C 来源，PASS 阈值 ≥ 80%）
#: - production_log: 生产日志抽样（A 来源，M3 阶段累积）
#: 注：aigc 主仓 excel-to-golden 导入的 case 带 "csv/<表名>/<行>" 溯源串，
#: 不在上述三桶内——schema 放宽为任意 str，三桶字面量仅作阈值键与文档。
CaseSource = Literal["business_seed", "llm_paraphrase", "production_log"]


class ConversationTurn(BaseModel):
    """单轮对话。"""

    model_config = ConfigDict(extra="allow")

    raw_content: str = ""
    quote_desc: str = ""


class GoldenCase(BaseModel):
    """主 golden schema（unified 格式）。"""

    model_config = ConfigDict(extra="allow")

    id: str
    category: str
    expected: dict[str, Any] = Field(default_factory=dict)
    type: str = "正案例"
    source: CaseSource | str = "business_seed"
    conversation: list[ConversationTurn] = Field(default_factory=list)
    # 兼容旧格式
    raw_content: str = ""
    quote_content: str | None = None
    notes: str | None = None


def load_golden(path: str | Path) -> list[GoldenCase]:
    """加载 golden.jsonl（支持 unified 和旧两种格式）。"""
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
            # unified 格式：raw_content 从 conversation 提取
            if obj.get("conversation") and not obj.get("raw_content"):
                obj["raw_content"] = obj["conversation"][0].get("raw_content", "")
            if obj.get("conversation") and not obj.get("quote_content"):
                obj["quote_content"] = obj["conversation"][0].get("quote_desc", "") or None
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


def filter_by_ids(cases: Iterable[GoldenCase], ids: list[str] | None) -> list[GoldenCase]:
    """按 case ID 精确过滤（如 ['g042', 'g001']）。"""
    if not ids:
        return list(cases)
    id_set = set(ids)
    return [c for c in cases if c.id in id_set]
