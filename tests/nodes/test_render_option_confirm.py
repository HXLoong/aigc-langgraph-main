"""确认结果由 Java 回执决定，不能根据本地 confirm 参数宣告成功。"""
from copy import deepcopy

import pytest

from app.nodes.render import render


@pytest.mark.parametrize("product,intent,order_id,receipt", [
    ("option", "confirm_order", "Q-LOCAL", "期权订单Q-BACKEND：已收到您的下单请求。"),
    ("swap", "confirm_order", "H-LOCAL", "互换订单H-BACKEND：已收到您的下单请求。"),
    ("option_close", "close_order_confirm", "CO-LOCAL", "期权平仓订单CO-BACKEND：已收到您的下单请求。"),
])
@pytest.mark.parametrize("has_receipt", [False, True])
async def test_confirmation_requires_backend_receipt(product, intent, order_id, receipt, has_receipt):
    state = {"product_type": product, "intent": intent,
             "confirm": {"action": "place", "orderList": [{"orderId": order_id}]}}
    if has_receipt:
        state.update(api_code=0, api_result=receipt)
    original = deepcopy(state)

    update = await render(state)

    if has_receipt:
        assert update["reply_text"] == receipt
    else:
        assert update["reply_text"] == "交易指令执行结果待核对，请勿重复提交，请联系交易员或运营核查。"
        assert "已收到" not in update["reply_text"]
        assert order_id not in update["reply_text"]
    assert state == original
