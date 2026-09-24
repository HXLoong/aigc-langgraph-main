"""期权订单范围与原文位置；只解析身份，不解释业务参数或执行动作。"""
from __future__ import annotations

import re
from dataclasses import dataclass

ORDER_ID_RE = re.compile(r"(?<![A-Za-z0-9-])Q-\d{8}-[A-Za-z0-9]{4,16}(?![A-Za-z0-9-])")
_NUMBER = r"[+-]?\d+|[零〇一二两三四五六七八九十百]+"
_SELECTOR = re.compile(
    rf"{ORDER_ID_RE.pattern}|序号\s*[:：]?\s*(?P<label>{_NUMBER})|"
    rf"第\s*(?P<position>{_NUMBER})\s*(?:个)?\s*(?:单(?!号)|笔|条)"
)
_LABEL = re.compile(rf"序号\s*[:：]?\s*({_NUMBER})")


class OrderScopeError(ValueError):
    """指定范围无法唯一绑定时阻止整批提交。"""


def extract_order_ids(text: str | None) -> list[str]:
    return list(dict.fromkeys(m[0] for m in ORDER_ID_RE.finditer(text or "")))


def _number(token: str) -> int:
    if token.lstrip("+-").isdigit():
        return int(token)
    digits = dict(zip("零一二三四五六七八九", range(10), strict=True))
    digits.update({"〇": 0, "两": 2})
    total = current = 0
    for char in token:
        if char in "十百":
            total += (current or 1) * (10 if char == "十" else 100)
            current = 0
        else:
            current = digits[char]
    return total + current


def quote_sequence_map(quote: str) -> dict[int, str]:
    """显式显示标签绑定相邻订单；提示模板中的示例不属于订单。"""
    ids = list(ORDER_ID_RE.finditer(quote))
    mapping: dict[int, str] = {}
    for marker in _LABEL.finditer(quote):
        line_start = quote.rfind("\n", 0, marker.start()) + 1
        before = [m for m in ids if line_start <= m.start() < marker.start()]
        after = next((m for m in ids if m.start() >= marker.end()), None)
        target = None
        if before and re.fullmatch(r"\s*[（(]\s*", quote[before[-1].end():marker.start()]):
            target = before[-1]
        elif after and re.fullmatch(
            r"\s*(?:(?:订单号|单号)\s*[:：]\s*|[:：]\s*)?", quote[marker.end():after.start()],
        ):
            target = after
        if target is None:
            line = quote[line_start:quote.find("\n", marker.start()) if "\n" in quote[marker.start():] else len(quote)]
            if re.search(r"请引用|例如|如只确认|如所有订单|如订单无误", line):
                continue
            raise OrderScopeError("引用订单序号无法唯一对应，请重新引用订单消息。")
        number = _number(marker[1])
        if number < 1 or (number in mapping and mapping[number] != target[0]):
            raise OrderScopeError("引用订单序号冲突，请重新引用订单消息。")
        mapping[number] = target[0]
    return mapping


@dataclass(frozen=True)
class OrderSelector:
    order_id: str
    start: int
    end: int
    text: str


def selectors(raw: str, quote: str) -> list[OrderSelector]:
    ids = extract_order_ids(quote)
    mapping: dict[int, str] | None = None
    result: list[OrderSelector] = []
    for match in _SELECTOR.finditer(raw):
        label, position = match.group("label"), match.group("position")
        if label is not None or position is not None:
            number = _number(label or position or "0")
            if label is not None:
                if mapping is None:
                    mapping = quote_sequence_map(quote) or dict(enumerate(ids, 1))
                order_id = mapping.get(number)
            else:
                order_id = ids[number - 1] if 0 < number <= len(ids) else None
            if not order_id:
                raise OrderScopeError("订单序号超出引用范围，请重新引用订单消息。")
        else:
            order_id = match[0]
        if result and re.fullmatch(r"[\s:：()（）]*", raw[result[-1].end:match.start()]):
            previous = result[-1]
            previous_is_id = ORDER_ID_RE.fullmatch(previous.text) is not None
            current_is_id = label is None and position is None
            if previous_is_id != current_is_id:
                if previous.order_id != order_id:
                    raise OrderScopeError("订单号与序号指向不同订单，请明确本次操作范围。")
                result[-1] = OrderSelector(order_id, previous.start, match.end(),
                                           raw[previous.start:match.end()])
                continue
        result.append(OrderSelector(order_id, match.start(), match.end(), match[0]))
    # 不能把无法识别的显式范围当成无范围，继而扩大为全部。
    remainder = _SELECTOR.sub("", raw)
    if re.search(
        r"序号|第\s*[零〇一二两三四五六七八九十百\d]|Q-|前几|后几|其中|除了|除外|以外|其余|"
        # 「最后一笔 / 前两笔 / 剩余的单」才是范围；「前收盘价」「最后半小时」不是
        r"(?:最后|前|后|剩余|余下|剩下)\s*(?:的)?\s*(?:[零〇一二两三四五六七八九十百\d]+|几)?"
        r"\s*(?:个)?\s*(?:笔|单(?!价)|条)|撤(?:掉|单)?\s*\d",
        remainder,
    ):
        raise OrderScopeError("无法确定指定订单范围，请提供完整订单号或明确序号。")
    return result
