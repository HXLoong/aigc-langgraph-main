"""检查联合结果的结构与来源，将接口值原样写入字段账本。"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from app.domain.request_cleaning import is_empty_parameter
from app.extraction.fields import EvidenceError, FieldRecord
from app.extraction.intent_evidence import intent_records
from app.extraction.sources import evidence_sources
from app.parsing.models import FieldEvidence, Instruction


def _leaves(value: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """枚举真实提供的非空字段，零值和 false 均必须保留。"""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}.{index}")
    elif value is not None:
        yield path, value


def _source_key(evidence: FieldEvidence) -> str:
    """引用原文和当前消息无需来源 ID，其它来源必须明确指定。"""
    if evidence.origin in {"raw", "quote"}:
        if evidence.reference is not None:
            raise EvidenceError("当前消息与引用证据不能指定其它来源")
        return evidence.origin
    if not evidence.reference or not evidence.reference.startswith(f"{evidence.origin}:"):
        raise EvidenceError("字段证据缺少来源定位")
    return evidence.reference


def verify_instruction(result: Instruction, state: Mapping[str, Any]) -> dict[str, FieldRecord]:
    """检查每个输出字段都有来源，并保留原值；不换算或校验业务数字。"""
    # 1. 意图必须有本轮依据，附件与只读上下文补充字段来源。
    product = "close" if result.product_type == "option_close" else result.product_type
    scope = f"{product}/parse"
    sources = evidence_sources(state, state.get("attachment_sources") or {})
    sources.update((state.get("parse_context") or {}).get("sources") or {})
    records = intent_records(result, state, scope=scope + ".intent", value=result.intent)
    by_path = {item.path: item for item in result.fields}
    if len(by_path) != len(result.fields):
        raise EvidenceError("字段证据路径重复")

    # 2. 只检查业务字段；候选选择已有独立的指针证据与范围校验。
    payload = result.model_dump(by_alias=True, exclude_none=True, exclude_unset=True)
    for key in ("product_type", "intent", "confidence", "evidence", "fields", "attachment_rows",
                "ticker_picks", "counterparty_picks"):
        payload.pop(key, None)
    paths = set()
    for path, value in _leaves(payload):
        paths.add(path)
        field_name = path.rsplit(".", 1)[-1]
        # 空占位没有可验证的业务事实；清洗节点保留原值诊断后将字段省略。
        # 订单身份与列表中的目标值仍按原有严格来源规则处理。
        if field_name not in {"orderId", "internalTradeId"} and not path.rsplit(".", 1)[-1].isdigit() and is_empty_parameter(value):
            continue
        item = by_path.get(path)
        if item is None:
            raise EvidenceError(f"字段缺少证据：{path}")
        origin = _source_key(item)
        if not item.text.strip() or item.text not in sources.get(origin, ""):
            raise EvidenceError(f"字段证据不在指定来源中：{path}")
        if item.origin == "history" and (
            field_name in {"orderId", "internalTradeId"}
            or path.startswith("order_ids.") or ".internalTradeIdList." in path
        ):
            raise EvidenceError("订单身份不能从未引用历史中补齐")
        if field_name in {"stockCode", "placeOrderWindCode"} and str(value) not in item.text:
            raise EvidenceError("标的必须保留原文或用户明确选择的候选")
        confirmation = result.intent in {"confirm_order", "confirm_cancel_order", "confirm_modify_order",
                                        "close_order_confirm", "close_order_cancel_confirm"}
        if path.startswith("orders.") and field_name not in {"orderId", "internalTradeId"}:
            order = payload["orders"][int(path.split(".", 2)[1])]
            # 既有订单的补参和确认只传当前增量，旧卡片不充当订单副本。
            current_only = confirmation or bool(order.get("orderId"))
            if current_only and item.origin not in {"raw", "attachment"}:
                raise EvidenceError("既有订单参数只能来自本次明确提供的增量")
        ledger_path = scope + "." + path.replace("orders.", "orderList.", 1)
        records[ledger_path] = FieldRecord(value=value, source="user", evidence=item.text,
            origin=origin, confidence=result.confidence, locked=True)
    if set(by_path) - paths:
        raise EvidenceError("字段证据指向不存在的输出字段")
    return records
