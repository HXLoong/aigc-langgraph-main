"""ticker 子图的 LLM 输出契约模型（ADR 0022 未决项：4 个提示词转 structured output）。

动态 key 映射（key = 输入项原文）统一包在命名字段 `results` 下。裸 object
schema（RootModel dict / 顶层数组）没有命名属性可填，DeepSeek function
calling 会把"参数对象"当成 schema 本身补全（2026-09 线上实测 3 个节点共 3 次
schema-echo：`{"additionalProperties": ...}` 类）；命名字段给模型提供参数锚点。
数据形态不变：`{"results": {...}}` 等价此前的裸 `{...}`。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class InferCodeOutput(BaseModel):
    """大模型推断对应标的代码的批量输出。"""

    results: dict[str, list[str]] = Field(
        description="key 必须为输入项原文；value 为字符串数组（代码在前、名称在后，期货合约末尾附兜底词）"
    )


class SplitKeywordsOutput(BaseModel):
    """标的代码和 code 拆分的批量输出。"""

    results: dict[str, list[str]] = Field(
        description="key 必须为输入项原文；value 为保守拆分后的关键词字符串数组"
    )


class JudgeTypeOutput(BaseModel):
    """大模型判断标的类型的批量输出。"""

    results: dict[str, str] = Field(
        description='key 必须为输入项原文；value 为 "EQUITY" | "FUND" | "FUTURE" | "INDEX" 之一，无法高置信判断时为空串'
    )


class RankOutput(BaseModel):
    """大模型排序并过滤后的输出（仅含过滤 + 排序后的 windCode，相关性最高在前）。"""

    ranked_codes: list[str] = Field(
        description="过滤并排序后的 windCode 列表；无相关标的返回空数组"
    )


__all__ = [
    "InferCodeOutput",
    "SplitKeywordsOutput",
    "JudgeTypeOutput",
    "RankOutput",
]
