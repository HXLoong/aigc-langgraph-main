"""option 订单号确定性提取（瘦身 P1：撤单 / 取消下单 / 确认撤单 / 查单 4 节点去 LLM 化）。

背景（对照 docs/swap-prompt-slimming-assessment.md 病灶 2）：原 4 个 LLM 节点
（request_cancel_order / cancel_order_request / confirm_cancel_order /
query_order_status）的唯一任务是提取 Q- 订单号——确定性正则即可完成，
零幻觉、零成本、零延迟。被替换的 4 个提示词文件已同批删除。

各意图的来源优先级 1:1 对照原提示词规约：
- request_cancel       raw 指定具体订单则用 raw；否则从 quote 取全部；均无 → [None]
- cancel_order_request 仅从 quote 取（用户引用确认卡并选择取消）；均无 → [None]
- confirm_cancel_order 仅从 quote 取（机器人撤单确认消息，多单全取）；均无 → [None]
- query_order_status   raw 优先，否则 quote；均无 → [None]

均无时返回 `[None]` 而不是 `[]`：与历史 LLM 输出形状一致（orderList 保留一条
orderId=null 的占位条目，下游接口据此查询近期全部订单）。
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
    """取消下单：仅从 quote 提取（引用卡片中的订单号）；均无 → [None]。"""
    return _first_nonempty(extract_order_ids(quote))


def extract_for_confirm_cancel(raw: str | None, quote: str | None) -> list[str | None]:
    """确认撤单：仅从 quote 提取（机器人撤单确认消息，可多单）；均无 → [None]。"""
    return _first_nonempty(extract_order_ids(quote))


def extract_for_query(raw: str | None, quote: str | None) -> list[str | None]:
    """查单：raw 优先，否则 quote；均无 → [None]。"""
    return _first_nonempty(extract_order_ids(raw), extract_order_ids(quote))


__all__ = [
    "ORDER_ID_RE",
    "extract_order_ids",
    "extract_for_request_cancel",
    "extract_for_cancel_place",
    "extract_for_confirm_cancel",
    "extract_for_query",
]
