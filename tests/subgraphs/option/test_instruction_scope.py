"""联合结果不能扩大原文或引用指定的订单范围。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.request_params import request_orders
from tests.joint_support import instruction_data

FIRST = "Q-20260918-0000000001"
SECOND = "Q-20260918-0000000002"
QUOTE = f"订单号：{FIRST}\n订单号：{SECOND}"


@pytest.mark.parametrize("raw", ["不要确认下单", "暂不确认下单", "先别确认下单", "不确认下单", "不用确认下单", "不需要确认下单", "是否确认下单", "确认下单吗", "确认下单？"])
async def test_negated_confirmation_cannot_execute(monkeypatch, raw):
    """即使模型误识别确认，执行节点仍阻止否定或疑问表达提交。"""
    backend = AsyncMock()
    monkeypatch.setattr("app.subgraphs.option.extract_confirm_place.prepare_option_request", backend)
    result = await option_extract_confirm_place({"raw_text": raw, "quote_content": QUOTE,
        "parsed_instruction": instruction_data("option", "confirm_order", raw,
            orders=[{"orderId": FIRST}], quote=QUOTE)})
    assert result.get("reply_text")
    backend.assert_not_called()


@pytest.mark.parametrize("raw,orders", [
    ("第3笔限价10", [{"orderId": FIRST, "limitPrice": 10}]),
    ("第2笔限价10", [{"orderId": FIRST, "limitPrice": 10}]),
    ("第2笔限价10", [{"orderId": FIRST}, {"orderId": SECOND}]),
])
def test_model_orders_must_match_current_selection(raw, orders):
    """错误序号、串单或额外订单不能靠合法引用单号蒙混过关。"""
    with pytest.raises(ValueError):
        request_orders({"raw_text": raw, "quote_content": QUOTE,
            "parsed_instruction": instruction_data("option", "place_order_from_quote", raw,
                orders=orders, quote=QUOTE)}, "place_order_from_quote")
