"""swap 订单号确定性提取(瘦身 P1:撤单/查单/三确认节点去 LLM 化)。

背景(docs/swap-prompt-slimming-assessment.md 病灶 2):原 5 个 LLM 节点
(cancel_order / query_order / confirm_order / confirm_cancel / confirm_modify)
的唯一任务是按格式 `H-YYYYMMDD-XXXXXXXXXX` 提取订单号——确定性正则即可完成,
零幻觉、零成本、零延迟。原提示词保留为非活跃资产(app/prompts/CLAUDE.md)。

各意图的来源优先级 1:1 对照原提示词规约:
- cancel:raw 明确指定优先("明确指定"),否则 quote 全部("默认范围:全部可操作订单")
- query:raw 优先,否则 quote
- confirm_order:quote 中全部(首现顺序去重、不遗漏),quote 无则 raw
- confirm_cancel / confirm_modify:quote 优先,否则 raw
均无 → [None](交后端按上下文兜底,形状与原 LLM 输出一致)。
"""
from __future__ import annotations

import re

#: H-YYYYMMDD-XXXXXXXXXX(8 位日期 + 10 位数字,与后端 SwapOrderIdGenerator 一致)
ORDER_ID_RE = re.compile(r"H-\d{8}-\d{10}")


def extract_order_ids(text: str | None) -> list[str]:
    """按首现顺序提取全部订单号并去重。"""
    if not text:
        return []
    seen: dict[str, None] = {}
    for m in ORDER_ID_RE.finditer(text):
        seen.setdefault(m.group(0))
    return list(seen)


def _first_nonempty(*candidates: list[str]) -> list[str | None]:
    for ids in candidates:
        if ids:
            return list(ids)
    return [None]


def extract_for_cancel(raw: str | None, quote: str | None) -> list[str | None]:
    """撤单:raw 明确指定的单号优先;否则处理 quote 中全部订单。"""
    return _first_nonempty(extract_order_ids(raw), extract_order_ids(quote))


def extract_for_query(raw: str | None, quote: str | None) -> list[str | None]:
    """查单:raw 优先,否则 quote。"""
    return _first_nonempty(extract_order_ids(raw), extract_order_ids(quote))


def extract_for_confirm_order(raw: str | None, quote: str | None) -> list[str | None]:
    """确认下单:quote 中全部订单号(不遗漏),quote 无则 raw。"""
    return _first_nonempty(extract_order_ids(quote), extract_order_ids(raw))


def extract_for_confirm_single(raw: str | None, quote: str | None) -> list[str | None]:
    """确认撤单/确认改单:quote 优先,否则 raw。"""
    return _first_nonempty(extract_order_ids(quote), extract_order_ids(raw))


__all__ = [
    "ORDER_ID_RE",
    "extract_order_ids",
    "extract_for_cancel",
    "extract_for_query",
    "extract_for_confirm_order",
    "extract_for_confirm_single",
]
