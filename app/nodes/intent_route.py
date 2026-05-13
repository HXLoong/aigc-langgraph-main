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
from app.llm.clients import get_qwen_thinking
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
    (re.compile(r"Q-\d{8}-[A-Z0-9]+"), "option_close"),
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
    """第 2 层：按 YAML 优先级表遍历，命中即 break（向后兼容接口）。"""
    detail = _match_keywords_with_token(text)
    return detail[0] if detail is not None else None


def _match_keywords_with_token(text: str) -> tuple[ProductType, str] | None:
    """第 2 层带 trace token 版本（E3.4 错例追溯用）。

    Returns:
        (product_type, hit_token) 命中时；hit_token 是触发匹配的 keyword 或 regex pattern。
        如裸"确认下单"被路由到 option 时返回 ('option', 'kw:确认下单')，
        便于 trace 中明示路由决策依据。
    """
    for rule in _KEYWORD_RULES:
        pt: ProductType = rule["product_type"]
        for kw in rule.get("keywords", []) or []:
            if kw in text:
                return pt, f"kw:{kw}"
        for pat in rule.get("regex_patterns", []) or []:
            if re.search(pat, text):
                return pt, f"re:{pat}"
    return None


# ============================================================
# 第 2.5 层：quote_content 产品标记快速路径
# ============================================================

#: 机器人回复中唯一标识产品的标记 → product_type
_QUOTE_MARKERS: list[tuple[str, ProductType]] = [
    ("-----场外期权询价详情-----", "option"),
    ("-----场外期权持仓详情-----", "option_close"),
    ("平仓申请已生成", "option_close"),
    ("-----互换订单参数-----", "swap"),
]


def _match_quote_marker(quote_content: str | None) -> ProductType | None:
    """第 2.5 层：quote_content 含机器人回复产品标记时直接路由，不走 LLM。

    只匹配 render 输出的唯一性标记，不做宽泛关键词匹配（避免误触发）。
    """
    if not quote_content:
        return None
    for marker, pt in _QUOTE_MARKERS:
        if marker in quote_content:
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
    llm = get_qwen_thinking().with_structured_output(ProductTypeOutput)
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
    match = _match_keywords_with_token(text)
    if match is not None:
        pt, hit_token = match
        return {
            "product_type": pt,
            "trace": [
                TraceEntry(
                    node="intent_route",
                    decision=f"rule:keyword[{hit_token}]→{pt}",
                )
            ],
        }

    # 第 2.5 层：quote_content 产品标记
    quote = state.get("quote_content")
    pt = _match_quote_marker(quote)
    if pt is not None:
        return {
            "product_type": pt,
            "trace": [
                TraceEntry(node="intent_route", decision=f"rule:quote_marker→{pt}")
            ],
        }

    # 第 3 层
    pt = await _classify_with_llm(text, quote_content=quote)
    return {
        "product_type": pt,
        "trace": [TraceEntry(node="intent_route", decision=f"llm→{pt}")],
    }


__all__ = ["intent_route", "ProductTypeOutput"]
