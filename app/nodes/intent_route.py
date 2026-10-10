"""无需模型的产品路由：订单及引用规则优先，歧义交给一次联合解析。"""
from __future__ import annotations

from typing import Any

from app.graph.safe_node import safe_node
from app.graph.state import AgentState, ProductType, TraceEntry
from app.nodes.route_rules import classify_trade_type

_LABEL_MAP: dict[str, ProductType] = {
    "互换-文本": "swap", "期权-文本": "option", "期权平仓-文本": "option_close",
}


def resolve_product_hint(state: AgentState) -> tuple[ProductType, str]:
    """主图与隔离解析节点共用相同的规则优先级，不读取测试期望。"""
    label = classify_trade_type(state.get("raw_text") or "", state.get("quote_content"))
    product: ProductType = _LABEL_MAP.get(label, "unknown")
    previous = state.get("product_type")
    if product == "unknown" and previous in ("swap", "option", "option_close"):
        return previous, "context"
    return product, "rule"


@safe_node
async def intent_route(state: AgentState) -> dict[str, Any]:
    """提供产品提示，不调用模型；联合解析同时补齐产品、意图和参数。"""
    # 1. 只依据本次文本及引用确定产品，Excel 本身不强制归为互换。
    if state.get("error") or state.get("reply_text"):
        return {}
    product, source = resolve_product_hint(state)
    return {"product_type": product, "swap_input_mode": "text",
            "trace": [TraceEntry(node="intent_route", decision=f"{source}→{product}")]}
