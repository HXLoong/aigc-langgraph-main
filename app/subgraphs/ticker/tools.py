"""ticker 子图的 4 个 ReAct 工具（Day 1 stub 阶段）。

Day 1：仅签名 + 简单 stub 行为，让 ReAct Agent 能编译 + 跑通最简 case。
后续 PR 实现真业务逻辑：
- #M2-Ticker-2 · tokenize 接 GOATS 词典 + LLM 兜底
- #M2-Ticker-3 · completeness + rank 接 securities-instrument/select
- #M2-Ticker-4 · infer_code 接 instrument-inference-prompt 动态片段（ADR 0013）
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool


@tool
def tokenize(raw_text: Annotated[str, "用户原话"]) -> list[str]:
    """把用户原话拆分为标的关键词候选 list。

    Day 1 stub：按空格 split。真实实现见 #M2-Ticker-2。
    """
    return [tok for tok in raw_text.split() if tok]


@tool
def completeness(
    keyword: Annotated[str, "标的关键词或代码"],
) -> dict[str, object]:
    """判断关键词是否是完整的标的代码（含交易所后缀）。

    Day 1 stub：检查后缀 .SH / .SZ / .HK / .HKEX。
    """
    suffixes = (".SH", ".SZ", ".HK", ".HKEX")
    is_complete = any(keyword.upper().endswith(s) for s in suffixes)
    return {"keyword": keyword, "is_complete": is_complete}


@tool
def rank(
    candidates: Annotated[list[str], "标的代码候选列表"],
) -> str:
    """排序候选并返回最佳。

    Day 1 stub：直接返回第一个非空候选。真实实现按 relevanceScore 排序，
    分差 ≥ 10 自动选最高，否则触发 HITL（#M2-Ticker-3 实施）。
    """
    for c in candidates:
        if c:
            return c
    return ""


@tool
def infer_code(
    keyword: Annotated[str, "中文简称或俗称"],
) -> str:
    """基于关键词推断完整标的代码。

    Day 1 stub：原样返回。真实实现见 #M2-Ticker-4，含动态 prompt 片段
    （`GET /admin-api/counterparty/info/instrument-inference-prompt`，ADR 0013）。
    """
    return keyword


# 工具列表（供 react_agent.py 注册到 ReAct Agent）
TICKER_TOOLS = [tokenize, completeness, rank, infer_code]


__all__ = ["TICKER_TOOLS", "tokenize", "completeness", "rank", "infer_code"]
