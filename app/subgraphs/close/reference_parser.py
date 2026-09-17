"""close.place_close 链 · 引用消息解析（纯函数）。

Dify 原节点：`平仓参数提取-引用消息解析`（code，id=1772677545585）。
输入：用户引用消息 quote_content + 原始消息 raw_content。
输出：供下游"获取订单信息"http 节点与 LLM 提取节点使用的确定性事实
（holdingMap / errorOrderIds / fullCloseIds / pureErrorOrderIds / ...）。

与 Dify 原版差异（工程适配，不改变行为）：
- 数组类输出保持 Python 原生 list/int/bool 类型，不转成 JSON 字符串/字符串化数字
  （Dify 侧转字符串是因为要塞进 variable-aggregator 文本占位符；我们在
  `place_close.py` 组装 LLM user message 时才做文本序列化）。
"""
from __future__ import annotations

import re
from typing import Any, TypedDict

from app.subgraphs.close.order_id import ORDER_ID_EXACT8_TOKEN, ORDER_ID_STRICT_TOKEN

_SEQ_RE = re.compile(r"序号[：:]\s*(\d+)")
_ORDER_ID_RE = re.compile(rf"单号[：:]\s*({ORDER_ID_EXACT8_TOKEN})")
_CONTRACT_RE = re.compile(r"合约编号[：:]\s*(OPT[G]?-[A-Z0-9]+)")
_ERROR_ID_PATTERNS = (
    re.compile(rf"期权平仓订单\[({ORDER_ID_STRICT_TOKEN})\]参数需要完善"),
    re.compile(rf"期权平仓订单({ORDER_ID_STRICT_TOKEN})（序号\d+）"),
)
_FULL_CLOSE_RE = re.compile(rf"期权平仓订单({ORDER_ID_STRICT_TOKEN})[：:].*?只能全部平仓")
_RAW_ORDER_ID_RE = re.compile(rf"({ORDER_ID_STRICT_TOKEN})")
_RAW_CONTRACT_RE = re.compile(r"(OPT[G]?-[A-Z0-9]+)")

_DETAIL_END_MARKERS = ("若以上订单执行平仓操作", "期权平仓订单")
_CLOSE_RESULT_MARKERS = ("以下平仓申请，请核对详情后确认", "参数需要完善", "只能全部平仓")


class ReferenceParseResult(TypedDict):
    messageType: str
    successOrders: list[dict[str, Any]]
    errorOrderIds: list[str]
    holdingMap: list[dict[str, Any]]
    fullCloseIds: list[str]
    pureErrorOrderIds: list[str]
    pureErrorOrderCount: int
    holdingMapCandidateCount: int
    hasSingleHoldingCandidate: bool
    singleHoldingCandidateOrderId: str | None
    orderIds: list[str]
    contractCodes: list[str]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _seq_positions(text: str) -> list[tuple[int, int]]:
    return [(m.start(), int(m.group(1))) for m in _SEQ_RE.finditer(text)]


def _parse_order_block(block: str) -> dict[str, Any]:
    order_id_match = _ORDER_ID_RE.search(block)
    return {
        "orderId": order_id_match.group(1) if order_id_match else None,
        "closeOrderNotionalDelta": None,
        "closeOrderType": None,
        "closeOrderPrice": None,
        "closeOrderPovRatio": None,
        "closeOrderAlgoStartTime": None,
        "closeOrderAlgoEndTime": None,
        "confirmFullClose": None,
    }


def _parse_success_orders(text: str) -> list[dict[str, Any]]:
    detail_end = len(text)
    for marker in _DETAIL_END_MARKERS:
        idx = text.find(marker)
        if idx != -1 and idx < detail_end:
            detail_end = idx

    positions = [p for p in _seq_positions(text) if p[0] < detail_end]
    orders: list[dict[str, Any]] = []
    for i, (start, _seq) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else detail_end
        block = text[start:end]
        order = _parse_order_block(block)
        if order["orderId"] and "【待补充】" not in block:
            orders.append(order)
    return orders


def _parse_error_order_ids(text: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for pattern in _ERROR_ID_PATTERNS:
        for match in pattern.finditer(text):
            oid = match.group(1)
            if oid not in seen:
                seen.add(oid)
                ids.append(oid)
    return ids


def _parse_full_close_order_ids(text: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for match in _FULL_CLOSE_RE.finditer(text):
        oid = match.group(1)
        if oid not in seen:
            seen.add(oid)
            ids.append(oid)
    return ids


def _parse_holding_map(text: str) -> list[dict[str, Any]]:
    positions = _seq_positions(text)
    holdings: list[dict[str, Any]] = []
    for i, (start, seq) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        block = text[start:end]
        order_id_match = _ORDER_ID_RE.search(block)
        contract_match = _CONTRACT_RE.search(block)
        holdings.append(
            {
                "seq": seq,
                "orderId": order_id_match.group(1) if order_id_match else None,
                "contractId": contract_match.group(1) if contract_match else None,
            }
        )
    return holdings


def parse_reference_message(
    quote_content: str | None, raw_content: str | None
) -> ReferenceParseResult:
    """平仓参数提取-引用消息解析（1:1 移植）。

    Args:
        quote_content: 用户引用的上一条消息内容。
        raw_content: 用户本轮原始输入。

    Returns:
        供 http 订单查询 + LLM 提取节点使用的确定性事实字典。
    """
    text = (quote_content or "").strip()
    raw = (raw_content or "").strip()

    message_type = "holding_list"
    success_orders: list[dict[str, Any]] = []
    error_order_ids: list[str] = []
    full_close_ids: list[str] = []
    holding_map: list[dict[str, Any]] = []

    if text:
        is_close_result = any(marker in text for marker in _CLOSE_RESULT_MARKERS)
        if is_close_result:
            message_type = "close_result"
            success_orders = _parse_success_orders(text)
            error_ids = _parse_error_order_ids(text)
            full_close_ids = _parse_full_close_order_ids(text)
            error_order_ids = _unique(error_ids + full_close_ids)
            full_close_ids = _unique(full_close_ids)
            holding_map = _parse_holding_map(text)
        else:
            holding_map = _parse_holding_map(text)

    full_close_id_set = set(full_close_ids)
    pure_error_order_ids = [oid for oid in error_order_ids if oid not in full_close_id_set]

    bindable = [item for item in holding_map if item.get("orderId")]
    has_single_candidate = len(bindable) == 1
    single_candidate_order_id = bindable[0]["orderId"] if has_single_candidate else None

    holding_order_ids = [item["orderId"] for item in holding_map if item.get("orderId")]
    raw_order_ids = _RAW_ORDER_ID_RE.findall(raw)
    order_ids = _unique(holding_order_ids + error_order_ids + raw_order_ids)
    contract_codes = _unique(_RAW_CONTRACT_RE.findall(raw))

    return ReferenceParseResult(
        messageType=message_type,
        successOrders=success_orders,
        errorOrderIds=error_order_ids,
        holdingMap=holding_map,
        fullCloseIds=full_close_ids,
        pureErrorOrderIds=pure_error_order_ids,
        pureErrorOrderCount=len(pure_error_order_ids),
        holdingMapCandidateCount=len(bindable),
        hasSingleHoldingCandidate=has_single_candidate,
        singleHoldingCandidateOrderId=single_candidate_order_id,
        orderIds=order_ids,
        contractCodes=contract_codes,
    )


__all__ = ["parse_reference_message", "ReferenceParseResult"]
