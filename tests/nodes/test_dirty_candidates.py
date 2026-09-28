"""脏业务标量必须到达清洗边界，不能由模型框架提前改成交易值。"""
from types import SimpleNamespace

import pytest

from tests.joint_support import instruction_data


@pytest.mark.parametrize("product,intent,order", [
    ("swap", "place_order_request", {"placeOrderQuantity": True, "placeOrderNotional": "100万"}),
    ("option", "new_inquiry", {"stockCode": "茅台", "limitPrice": "错误价格"}),
    ("option_close", "close_order_request", {"internalTradeId": "OPT-1", "closeOrderPrice": "100元"}),
])
async def test_parse_preserves_dirty_scalar_types(monkeypatch, product, intent, order) -> None:
    """实际 PromptSpec 模型解析仍通过，非空字段的真实来源继续核验。"""
    from app.nodes import parse_instruction as module

    raw = "互换期权平仓 茅台 OPT-1 100万 错误价格 100元"
    data = instruction_data(product, intent, raw, orders=[order])

    def structured(schema):
        async def invoke(messages):
            payload = {"instruction": data} if schema.__name__ == "CrossProductInstruction" else data
            return schema.model_validate(payload)
        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(module, "resolve_product_hint", lambda state: (product, "test"))
    monkeypatch.setattr(module, "get_llm_standard", lambda: SimpleNamespace(with_structured_output=structured))
    result = await module.parse_instruction({"raw_text": raw})
    assert result.get("error") is None
    assert result["parsed_instruction"]["orders"] == [order]
    if product == "swap":
        assert result["parsed_instruction"]["orders"][0]["placeOrderQuantity"] is True


async def test_null_placeholder_does_not_require_invented_evidence(monkeypatch) -> None:
    """未提供值被模型写为 null 字符串时，不要求伪造一个原文来源。"""
    from app.nodes import parse_instruction as module

    data = instruction_data("option", "new_inquiry", "期权茅台询价", orders=[{"stockCode": "茅台"}])
    data["orders"][0]["notionalAmount"] = "NULL"

    def structured(schema):
        async def invoke(messages):
            return schema.model_validate(data)
        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(module, "resolve_product_hint", lambda state: ("option", "test"))
    monkeypatch.setattr(module, "get_llm_standard", lambda: SimpleNamespace(with_structured_output=structured))
    result = await module.parse_instruction({"raw_text": "期权茅台询价"})
    assert result.get("error") is None
    assert result["parsed_instruction"]["orders"][0]["notionalAmount"] == "NULL"
