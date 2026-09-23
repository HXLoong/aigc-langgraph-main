"""测试输入的显式订单引用；禁止猜测或借用其它轮次的订单。"""
import re

from harness.references import resolve_expected_references

_ORDER_ID = re.compile(r"(?<![A-Za-z0-9-])(?:CO|Q|H)-\d{8}-[A-Za-z0-9]+(?![A-Za-z0-9-])")
PREVIOUS_ORDER_ID = "{{previous_order_id}}"
_HOLDING_REFERENCE = re.compile(r"\{\{previous_holding_contract_id(?::([1-9][0-9]*))?\}\}")


class ScenarioInputError(ValueError):
    """用例输入所需的业务引用或选择器不满足前置条件。"""


def resolve_order_reference(text: str, previous_reply: str) -> str:
    if PREVIOUS_ORDER_ID in text:
        identifiers = set(_ORDER_ID.findall(previous_reply))
        if len(identifiers) != 1:
            raise ValueError("previous_order_id 要求上一轮回复包含唯一订单号")
        text = text.replace(PREVIOUS_ORDER_ID, identifiers.pop())

    def holding(match: re.Match[str]) -> str:
        reference: dict[str, str | int] = {"$ref": "quote.holding_contract"}
        if match[1] is not None:
            reference["position"] = int(match[1])
        try:
            value = resolve_expected_references(reference, previous_reply)
        except ValueError as exc:
            raise ScenarioInputError("无法绑定上一轮持仓合约：" + str(exc)) from exc
        if not isinstance(value, str):
            raise ScenarioInputError("持仓引用必须解析为一个合约")
        return value

    text = _HOLDING_REFERENCE.sub(holding, text)
    if "{{previous_holding_contract_id" in text:
        raise ScenarioInputError("持仓引用选择器必须为正整数")
    return text
