"""测试输入的显式订单引用；禁止猜测或借用其它轮次的订单。"""
import re

_ORDER_ID = re.compile(r"(?<![A-Za-z0-9-])(?:CO|Q|H)-\d{8}-[A-Za-z0-9]+(?![A-Za-z0-9-])")
PREVIOUS_ORDER_ID = "{{previous_order_id}}"


def resolve_order_reference(text: str, previous_reply: str) -> str:
    if PREVIOUS_ORDER_ID not in text:
        return text
    identifiers = set(_ORDER_ID.findall(previous_reply))
    if len(identifiers) != 1:
        raise ValueError("previous_order_id 要求上一轮回复包含唯一订单号")
    return text.replace(PREVIOUS_ORDER_ID, identifiers.pop())
