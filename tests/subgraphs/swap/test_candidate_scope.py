"""补参的来源边界由代码守护，不能靠模型承诺不复制旧参数。"""
from app.subgraphs.swap.place_order import swap_place_order
from tests.joint_support import instruction_data


async def test_quote_price_cannot_be_copied_into_modification():
    """原文只改数量时，引用里的旧价格不得成为新的提交字段。"""
    raw, quote = "数量改为2000股", "H-20260918-0000000001 限价10"
    parsed = instruction_data("swap", "place_order_request", raw, quote=quote,
        orders=[{"orderId": "H-20260918-0000000001", "placeOrderPrice": 10, "placeOrderQuantity": 2000}])
    parsed["fields"][1].update(origin="quote", text="限价10")
    result = await swap_place_order({"raw_text": raw, "quote_content": quote, "parsed_instruction": parsed})
    assert result.get("error") and result["error"].code == "E2"
    assert not result.get("place_params")
