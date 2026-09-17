"""swap 订单号确定性提取(瘦身 P1:撤单/查单/三确认节点去 LLM 化)。

背景(docs/swap-prompt-slimming-assessment.md 病灶 2):原 5 个 LLM 节点
(cancel_order / query_order / confirm_order / confirm_cancel / confirm_modify)
的唯一任务是按格式 `H-YYYYMMDD-XXXXXXXXXX` 提取订单号——确定性正则即可完成,
零幻觉、零成本、零延迟。被替换的 5 个节点提示词已同批删除
(另含旧合并版快照 confirm.md；零加载点即删,ADR 0022)。

各意图的来源优先级 1:1 对照原提示词规约:
- cancel:raw 的单号/序号/标的/合约共同限定，无法确定时抛 CancelScopeError；无范围才取 quote 全部
- query:raw 优先,否则 quote
- confirm_order:quote 中全部(首现顺序去重、不遗漏),quote 无则 raw
- confirm_cancel / confirm_modify:quote 优先,否则 raw
均无 → [None](撤单仅在未指定范围时兜底,形状与原 LLM 输出一致)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: H-YYYYMMDD-XXXXXXXXXX(8 位日期 + 10 位数字,与后端 SwapOrderIdGenerator 一致)
ORDER_ID_RE = re.compile(r"H-\d{8}-\d{10}")

_NUMBER = r"[零〇一二两三四五六七八九十百\d]+"
_ORDINAL = re.compile(rf"(?:第\s*({_NUMBER})\s*[笔个条单]|序号\s*[:：]?\s*({_NUMBER}))")
_LABELS = r"大合约编号|合约编号|标的代码|标的名称"
_FIELDS = re.compile(rf"({_LABELS})\s*[:：]\s*(.*?)(?=(?:{_LABELS})\s*[:：]|[\r\n]|$)")


class CancelScopeError(ValueError):
    """当前撤单限定无法由引用中的订单信息唯一确定。"""


def _number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    digits.update({"〇": 0, "两": 2})
    total = current = 0
    for char in value:
        if char in "十百":
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        else:
            current = digits[char]
    return total + current


@dataclass
class _QuotedOrder:
    order_id: str
    ordinals: set[int] = field(default_factory=set)
    fields: dict[str, set[str]] = field(default_factory=dict)


def _quoted_orders(quote: str) -> list[_QuotedOrder]:
    """先按卡片/编号分块，再按订单号分块；重复订单合并元数据。"""
    quote = re.sub(
        rf"(?m)^([ \t]*{_NUMBER}[.、)）])[ \t]*\r?\n(?=-+场外收益互换)",
        r"\1 ", quote,
    )
    sections = re.split(
        rf"(?m)(?=^[ \t]*(?:{_NUMBER}[.、)）]\s|-+场外收益互换))",
        quote,
    )
    orders: dict[str, _QuotedOrder] = {}
    for section in sections:
        matches = list(ORDER_ID_RE.finditer(section))
        starts = [0]
        for previous, match in zip(matches, matches[1:], strict=False):
            prefix = section[previous.end():match.start()]
            header = re.search(
                rf"(?:序号\s*[:：]?\s*{_NUMBER}\s*)?(?:订单号|单号|订单)\s*[:：]?\s*$",
                prefix,
            )
            starts.append(previous.end() + header.start() if header else match.start())
        for index, match in enumerate(matches):
            end = starts[index + 1] if index + 1 < len(starts) else len(section)
            block = section[starts[index]:end]
            order_id = match.group()
            order = orders.setdefault(order_id, _QuotedOrder(order_id))
            ordinal = re.search(rf"序号\s*[:：]?\s*({_NUMBER})", block)
            if ordinal is None:
                ordinal = re.match(rf"\s*({_NUMBER})[.、)）]\s", block)
            if ordinal:
                order.ordinals.add(_number(ordinal.group(1)))
            for label, value in _FIELDS.findall(block):
                key = "合约编号" if label == "大合约编号" else label
                if value.strip():
                    order.fields.setdefault(key, set()).add(value.strip().upper())
    return list(orders.values())


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
    """同类限定取并集，不同类限定取交集；未解析的限定绝不扩大撤单范围。"""
    remaining = (raw or "").upper()
    explicit_ids = extract_order_ids(remaining)
    remaining = ORDER_ID_RE.sub(" ", remaining)
    orders = _quoted_orders(quote or "")
    constraints: list[set[str]] = []
    if explicit_ids:
        constraints.append(set(explicit_ids))

    ordinals = {_number(a or b) for a, b in _ORDINAL.findall(remaining)}
    remaining = _ORDINAL.sub(" ", remaining)
    if ordinals:
        numbered = any(order.ordinals for order in orders)
        selected: set[str] = set()
        for ordinal in ordinals:
            matches = {
                order.order_id for index, order in enumerate(orders, 1)
                if ordinal in (order.ordinals if numbered else {index})
            }
            if len(matches) != 1:
                raise CancelScopeError("引用序号不存在或不唯一")
            selected.update(matches)
        constraints.append(selected)

    # 只从引用的字段值建立身份关系，不推断证券名称或合约映射。
    matched_fields = set()
    for label in ("合约编号", "标的代码", "标的名称"):
        aliases = {value for order in orders for value in order.fields.get(label, set())}
        selected = set()
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = re.compile(r"(?<![A-Z0-9_.-])" + re.escape(alias) + r"(?![A-Z0-9_.-])")
            if pattern.search(remaining):
                selected.update(order.order_id for order in orders if alias in order.fields.get(label, set()))
                remaining = pattern.sub(" ", remaining)
        if selected:
            constraints.append(selected)
            matched_fields.add(label)

    if "合约" in remaining and "合约编号" not in matched_fields:
        raise CancelScopeError("缺少可验证的合约限定")
    if "标的" in remaining and not matched_fields.intersection({"标的代码", "标的名称"}):
        raise CancelScopeError("缺少可验证的标的限定")

    # 解析后的余文只能是动作、范围连接词和礼貌用语；未知限定请求补充。
    remaining = re.sub(
        r"取消下单|取消订单|全部撤单|撤销|撤掉|撤单|取消|全撤|撤|"
        r"大合约编号|合约编号|合约|标的代码|标的名称|标的|订单号|单号|订单|"
        r"麻烦|帮我|请|谢谢|全部|所有|都|把|将|的|和|及|与|还有|仅|只",
        "", remaining,
    )
    if re.search(r"[\w\u4e00-\u9fff]", remaining):
        raise CancelScopeError("无法解析撤单限定")
    if not constraints:
        return _first_nonempty(extract_order_ids(quote))
    selected = set.intersection(*constraints)
    if not selected:
        raise CancelScopeError("撤单限定冲突或引用不足")
    source = explicit_ids or [order.order_id for order in orders]
    return [order_id for order_id in source if order_id in selected]


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
    "CancelScopeError",
    "ORDER_ID_RE",
    "extract_order_ids",
    "extract_for_cancel",
    "extract_for_query",
    "extract_for_confirm_order",
    "extract_for_confirm_single",
]
