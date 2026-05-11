"""一级路由节点（ADR 0015）。

三层处理：
1. 订单号正则匹配（最高优先级，业务硬约定）
2. 关键词优先级表（`app/prompts/router/keywords.yaml`）
3. LLM 兜底（仅规则全部未命中或冲突时）

LLM 兜底也不确定 → product_type = "unknown" → 主图 cascade 防御走 fallback。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ProductType, TraceEntry
from app.llm.clients import get_qwen_structured
from app.prompts import load_prompt

logger = logging.getLogger(__name__)


# ============================================================
# 第 1 层：订单号正则（业务硬约定，最高优先级）
# ============================================================

#: 订单号 prefix → product_type 映射（ADR 0015）
_ORDER_NO_PATTERNS: list[tuple[re.Pattern[str], ProductType]] = [
    (re.compile(r"H-\d{8}-[A-Z0-9]+"), "swap"),
    (re.compile(r"OPT-\d{8}-[A-Z0-9]+"), "option"),
    (re.compile(r"CO-\d{8}-[A-Z0-9]+"), "option_close"),
    (re.compile(r"OPTG-[A-Z0-9]+"), "option_close"),
]


def _match_order_no(text: str) -> ProductType | None:
    """第 1 层：扫订单号正则。命中返回 product_type，否则 None。"""
    for pattern, pt in _ORDER_NO_PATTERNS:
        if pattern.search(text):
            return pt
    return None


# ============================================================
# 第 2 层：关键词优先级表（YAML 单文件，业务方可维护）
# ============================================================

_KEYWORDS_YAML = (
    Path(__file__).parent.parent / "prompts" / "router" / "keywords.yaml"
)


def _load_keyword_rules() -> list[dict[str, Any]]:
    """启动时加载一次（不重复 IO）。"""
    text = _KEYWORDS_YAML.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data.get("priority_rules", [])


_KEYWORD_RULES: list[dict[str, Any]] = _load_keyword_rules()


def _match_keywords(text: str) -> ProductType | None:
    """第 2 层：按 YAML 优先级表遍历，命中即 break。"""
    for rule in _KEYWORD_RULES:
        pt: ProductType = rule["product_type"]
        for kw in rule.get("keywords", []) or []:
            if kw in text:
                return pt
        for pat in rule.get("regex_patterns", []) or []:
            if re.search(pat, text):
                return pt
    return None


# ============================================================
# 第 3 层：LLM 兜底（standard 模型 + structured output）
# ============================================================


class ProductTypeOutput(BaseModel):
    """LLM 兜底输出 schema。"""

    product_type: Literal["swap", "option", "option_close", "unknown"]


async def _classify_with_llm(
    text: str, quote_content: str | None = None
) -> ProductType:
    """第 3 层：LLM 兜底分类。

    传 quote_content 让 LLM 利用引用消息上下文判断（如"确认第二笔" + 引用
    含期权报价 → option）。
    """
    prompt = load_prompt("router", "product_type")
    llm = get_qwen_structured().with_structured_output(ProductTypeOutput)
    user_text = prompt.render_user(raw_text=text)
    if quote_content:
        user_text += f"\n\n引用消息（上下文）：\n{quote_content}"
    result: Any = await llm.ainvoke(
        [
            ("system", prompt.system),
            ("user", user_text),
        ]
    )
    return result.product_type


# ============================================================
# 节点函数
# ============================================================


@safe_node
async def intent_route(state: AgentState) -> dict[str, Any]:
    """一级路由节点（ADR 0015）。

    出参约定：
    - `product_type`: 4 类之一（swap / option / option_close / unknown）
    - `trace`: 单条 TraceEntry，`decision` 字段记录决策来源
      - `rule:order_no→<pt>` · 第 1 层订单号正则命中
      - `rule:keyword→<pt>` · 第 2 层关键词命中
      - `llm→<pt>` · 第 3 层 LLM 兜底
    """
    text = state.get("raw_text", "") or ""

    # 第 1 层
    pt = _match_order_no(text)
    if pt is not None:
        return {
            "product_type": pt,
            "trace": [
                TraceEntry(node="intent_route", decision=f"rule:order_no→{pt}")
            ],
        }

    # 第 2 层
    pt = _match_keywords(text)
    if pt is not None:
        return {
            "product_type": pt,
            "trace": [
                TraceEntry(node="intent_route", decision=f"rule:keyword→{pt}")
            ],
        }

    # 第 3 层
    quote = state.get("quote_content")
    pt = await _classify_with_llm(text, quote_content=quote)
    return {
        "product_type": pt,
        "trace": [TraceEntry(node="intent_route", decision=f"llm→{pt}")],
    }


__all__ = ["intent_route", "ProductTypeOutput"]
