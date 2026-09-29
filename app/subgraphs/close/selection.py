"""平仓目标只绑定用户本次明确的编号、合约或引用序号。"""
from __future__ import annotations

import re
from typing import Any

from app.domain.numerals import require_ordinal
from app.domain.order_ids import CLOSE_ORDER_ID_RE, CONTRACT_CODE_RE
from app.extraction.fields import EvidenceError
from app.graph.state import AgentState
from app.subgraphs.close.reference_parser import parse_reference_message

_POSITION = re.compile(r"(序号|第)\s*([零〇一二两三四五六七八九十百\d]+)")


def _matches(order: dict[str, Any], target: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """比较明确身份；只有同一条只读记录才能桥接订单号与合约号。"""
    comparable = [key for key in ("orderId", "internalTradeId") if order.get(key) and target.get(key)]
    if comparable:
        return all(order[key] == target[key] for key in comparable)
    for row in rows:
        identity = {"orderId": row.get("orderId"), "internalTradeId": row.get("contractCode")}
        if all(not value or identity.get(key) == value for key, value in target.items()) and all(
            not order.get(key) or order[key] == identity.get(key) for key in identity
        ):
            return True
    return False


def validate_close_selection(state: AgentState, orders: list[dict[str, Any]]) -> None:
    """拒绝丢单、扩单和身份错配，不判断订单权限、状态或金额。"""
    # 1. 从本次原文和引用建立允许的身份集合，历史不用于本次选择。
    raw, quote = state.get("raw_text") or "", state.get("quote_content") or ""
    parsed = parse_reference_message(quote, raw)
    holdings = [{"orderId": row.get("orderId"), "internalTradeId": row.get("contractId")}
                for row in parsed["holdingMap"]]
    selected: list[dict[str, Any]] = [{"orderId": match[0]} for match in CLOSE_ORDER_ID_RE.finditer(raw)]
    selected.extend({"internalTradeId": match[0]} for match in CONTRACT_CODE_RE.finditer(raw))
    # 单号或合约若唯一命中当前引用，检查时保留该条目的完整身份对。
    # 这里只收紧选择范围，不往实际请求补字段或读取历史订单。
    for index, target in enumerate(selected):
        matches = [holding for holding in holdings
                   if all(holding.get(key) == value for key, value in target.items())]
        if len(matches) == 1:
            selected[index] = matches[0]
    for marker in _POSITION.finditer(raw):
        number = require_ordinal(marker[2])
        if marker[1] == "序号":
            positions = [i for i, row in enumerate(parsed["holdingMap"]) if row["seq"] == number]
        else:
            positions = [number - 1] if 1 <= number <= len(holdings) else []
        if len(positions) != 1:
            raise EvidenceError("平仓序号无法唯一对应本次引用")
        selected.append(holdings[positions[0]])
    allowed = selected or holdings
    if not allowed:
        allowed = [{"orderId": match[0]} for match in CLOSE_ORDER_ID_RE.finditer(quote)]
        allowed += [{"internalTradeId": match[0]} for match in CONTRACT_CODE_RE.finditer(quote)]

    # 2. 每个提交目标都必须可追踪；明确指定多个目标时不能静默漏掉其中一个。
    rows = (state.get("parse_context") or {}).get("orders") or []
    if not orders or any(not (order.get("orderId") or order.get("internalTradeId")) for order in orders):
        raise EvidenceError("平仓目标缺少订单号或合约编号")
    if any(not any(_matches(order, target, rows) for target in allowed) for order in orders):
        raise EvidenceError("平仓目标超出本次原文或引用范围")
    if selected and any(not any(_matches(order, target, rows) for order in orders) for target in selected):
        raise EvidenceError("本次指定的平仓目标未完整提交")
