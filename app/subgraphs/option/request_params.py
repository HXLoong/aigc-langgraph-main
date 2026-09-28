"""读取期权联合结果并检查本次订单范围，不从历史重建业务参数。"""
from __future__ import annotations

from typing import Any

from app.extraction.fields import EvidenceError, FieldRecord
from app.extraction.locks import protect_orders
from app.graph.state import AgentState
from app.parsing.evidence import verify_instruction
from app.parsing.models import OptionInstruction
from app.subgraphs.option.order_scope import extract_order_ids, selectors


def request_orders(
    state: AgentState, intent: str,
) -> tuple[list[dict[str, Any]], dict[str, FieldRecord]]:
    """保留本次稀疏字段，并验证模型给出的订单号属于用户选择。"""
    # 1. 相同解析结果在独立节点回放时仍需校验来源。
    parsed = OptionInstruction.model_validate(state.get("parsed_instruction") or {})
    if parsed.intent != intent:
        raise EvidenceError("节点动作与本次联合解析意图不一致")
    records = verify_instruction(parsed, state)
    orders = [order.model_dump(exclude_none=True, exclude_unset=True) for order in parsed.orders]

    # 2. 只验证订单身份，不对价格、金额、期限作业务处理。
    raw, quote = state.get("raw_text") or "", state.get("quote_content") or ""
    selected = list(dict.fromkeys(item.order_id for item in selectors(raw, quote)))
    allowed = set(selected or extract_order_ids(raw) or extract_order_ids(quote))
    submitted = [order["orderId"] for order in orders if order.get("orderId")]
    if any(order_id not in allowed for order_id in submitted):
        raise EvidenceError("订单号不属于本次输入或引用选择")
    if selected and set(submitted) != set(selected):
        raise EvidenceError("提交订单与本次明确选择的范围不一致")
    # 在调用 Java 前检查字段锁；不能先验范围，再让边界锁悄悄换成其它订单。
    _, rejected = protect_orders(state, orders, product="option")
    if rejected:
        raise EvidenceError("本次参数与已锁定字段冲突，请重新明确本次订单和参数")
    return orders, records
