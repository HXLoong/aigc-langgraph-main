"""互换内部准备图消费联合结果，不调用模型或后端，也不填业务默认。"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.clients import _ChatLLM
from app.subgraphs.swap.place_order import swap_place_order
from tests.joint_support import instruction_data


@pytest.mark.parametrize("raw,orders", [
    ("互换买茅台100股", [{"placeOrderWindCode": "茅台", "placeOrderQuantity": 100, "placeOrderOrderDirection": "BUY"}]),
    ("甲证券 -120股 VWAP全天", [{"placeOrderWindCode": "甲证券", "placeOrderQuantity": -120, "placeOrderAlgorithmType": "VWAP"}]),
    ("腾讯限价12.345", [{"placeOrderWindCode": "腾讯", "placeOrderPrice": 12.345}]),
    ("甲证券100股乙证券200股", [{"placeOrderWindCode": "甲证券", "placeOrderQuantity": 100}, {"placeOrderWindCode": "乙证券", "placeOrderQuantity": 200}]),
])
async def test_preparation_preserves_each_provided_value(monkeypatch, raw, orders):
    """模型已经给出接口值；代码保持符号、精度、订单数和字段缺省。"""
    model = MagicMock(side_effect=AssertionError("不允许额外模型"))
    backend = AsyncMock(side_effect=AssertionError("准备图不允许交易"))
    monkeypatch.setattr(_ChatLLM, "with_structured_output", model)
    monkeypatch.setattr("app.tools.swap_client.SwapClientHttpx.operate", backend)
    result = await swap_place_order({"raw_text": raw, "parsed_instruction": instruction_data("swap", "place_order_request", raw, orders=orders)})
    assert not result.get("error"), result
    assert result["place_params"]["orderList"] == orders
    assert result["expected_action"] == "place"
    model.assert_not_called()
    backend.assert_not_called()


async def test_foreign_order_id_cannot_enter_prepared_request():
    """编号不在当前输入或引用中即停止，不能用合法格式代替本次选择。"""
    raw = "改限价10"
    result = await swap_place_order({"raw_text": raw, "parsed_instruction": instruction_data("swap", "place_order_request", raw,
        orders=[{"orderId": "H-20260922-0000000001", "placeOrderPrice": 10}])})
    assert result.get("error")
    assert not result.get("place_params")
