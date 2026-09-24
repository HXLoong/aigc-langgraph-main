"""option 订单号确定性提取（撤单 / 取消下单 / 确认撤单 / 查单 4 个节点共用）。

用正则提取 Q- 订单号，不调用 LLM。各意图的来源优先级：
- request_cancel       raw 指定具体订单则用 raw；否则从 quote 取全部；均无 → [None]
- cancel_order_request 只取消 quote 中的订单；raw 指定则只取指定的几笔；无 quote → [None]
- confirm_cancel_order 仅从 quote 取（机器人撤单确认消息，多单全取）；均无 → [None]
- query_order_status   raw 优先，否则 quote；均无 → [None]

均无时返回 `[None]` 而不是 `[]`：orderList 保留一条 orderId=null 的占位条目，
下游接口据此查询近期全部订单。
"""
from __future__ import annotations

import re

from app.subgraphs.option.order_scope import (
    ORDER_ID_RE,
    OrderScopeError,
    extract_order_ids,
    selectors,
)


def _first_nonempty(*candidates: list[str]) -> list[str | None]:
    for ids in candidates:
        if ids:
            return list(ids)
    return [None]


def extract_for_request_cancel(raw: str | None, quote: str | None) -> list[str | None]:
    """指定范围必须完整解析；裸撤单仍默认引用全部，均无 → [None]。"""
    if re.search(r"(?:不|别|不要|不用|无需|勿)\s*(?:撤|取消)|(?:撤|取消)\S*\s*(?:不要|不行)", raw or ""):
        raise OrderScopeError("撤单范围含否定指令，请明确需要撤销的订单。")
    selected = selectors(raw or "", quote or "")
    if selected:
        return list(dict.fromkeys(item.order_id for item in selected))
    return _first_nonempty(extract_order_ids(quote))


def extract_for_cancel_place(raw: str | None, quote: str | None) -> list[str | None]:
    """取消下单：只取消引用里的订单；raw 指定（第N笔 / 序号 / 单号）则只取指定的几笔。

    指定范围无法解析或指向引用外的订单 → OrderScopeError；无引用 → [None]（raw 单号不参与）。
    """
    quoted = extract_order_ids(quote)
    if not quoted:
        return [None]
    selected = list(dict.fromkeys(item.order_id for item in selectors(raw or "", quote or "")))
    if any(order_id not in quoted for order_id in selected):
        raise OrderScopeError("指定的订单不在引用消息中，请引用对应订单消息后重新取消。")
    result: list[str | None] = list(selected or quoted)
    return result


def extract_for_query(raw: str | None, quote: str | None) -> list[str | None]:
    """查单：raw 优先，否则 quote；均无 → [None]。"""
    return _first_nonempty(extract_order_ids(raw), extract_order_ids(quote))


__all__ = [
    "ORDER_ID_RE",
    "extract_order_ids",
    "extract_for_request_cancel",
    "extract_for_cancel_place",
    "extract_for_query",
]
