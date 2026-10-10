"""平仓引用身份解析；只提取订单、合约和序号，不解释交易数值。"""
from __future__ import annotations

import re
from typing import Any, TypedDict

from app.domain.confirmation import confirmation_attempt
from app.domain.order_ids import CLOSE_ORDER_ID_EXACT8_TOKEN as ORDER_ID_EXACT8_TOKEN
from app.domain.order_ids import CLOSE_ORDER_ID_STRICT_TOKEN as ORDER_ID_STRICT_TOKEN

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
_NON_PLACE_ACTION = re.compile(r"查询|查一下|查下|查看|查持仓|查订单|查进度|持仓查询|订单查询|撤单|撤销|取消|撤掉|撤回|撤了")
_CLOSE_ACTION = re.compile(r"平仓|全平|平掉|平多|平空|平一半|平\s*[零一二两三四五六七八九十百\d]|全部平")
_CLOSE_PARAMETERS = re.compile(
    r"限价|市价|POV|TWAP|最大跟量|积极跟量|名义本金|金额|价格|跟量|保留|剩余|留\s*\d"
    r"|\d+(?:\.\d+)?\s*(?:%|％|万|亿|元|[wW]|成|分钟)|\d{1,2}:\d{2}", re.I,
)


def needs_close_order_context(raw_content: str | None, quote_content: str | None) -> bool:
    """仅本次明确平仓或引用订单补参需要预查询；身份本身不触发读取。"""
    raw = (raw_content or "").strip()
    quote = quote_content or ""
    if not raw or confirmation_attempt(raw) or _NON_PLACE_ACTION.search(raw):
        return False
    if re.search(r"是否|能否|如果|假如|[?？]|(?:不要|别|不需要|不想)\s*(?:平|撤)", raw):
        return False
    if _CLOSE_ACTION.search(raw):
        return True
    if "持仓" in raw or "可平" in raw:
        return False
    referenced_close = bool(_RAW_ORDER_ID_RE.search(quote) or _RAW_CONTRACT_RE.search(quote))
    current_target = bool(_RAW_ORDER_ID_RE.search(raw) or _RAW_CONTRACT_RE.search(raw))
    return bool((referenced_close or current_target) and _CLOSE_PARAMETERS.search(raw))


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
    """按首次出现顺序去重身份，不重排用户选择。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _seq_positions(text: str) -> list[tuple[int, int]]:
    """读取引用中的明确序号及其原始位置。"""
    return [(m.start(), int(m.group(1))) for m in _SEQ_RE.finditer(text)]


def _parse_order_block(block: str) -> dict[str, Any]:
    """从单个引用块读取单号与合约身份。"""
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
    """从成功回执的真实订单块读取身份映射。"""
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
    """提取错误回执中明确提及的订单身份。"""
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
    """提取引用中明确的全平订单身份。"""
    ids: list[str] = []
    seen: set[str] = set()
    for match in _FULL_CLOSE_RE.finditer(text):
        oid = match.group(1)
        if oid not in seen:
            seen.add(oid)
            ids.append(oid)
    return ids


def _parse_holding_map(text: str) -> list[dict[str, Any]]:
    """保留持仓引用中的序号、单号和合约对应关系。"""
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


__all__ = ["parse_reference_message", "ReferenceParseResult", "needs_close_order_context"]
