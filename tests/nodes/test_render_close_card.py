"""平仓卡由 Java 生成；本地订单、标的和引用不能补写回执。"""
from copy import deepcopy

import pytest

from app.nodes.render import render


@pytest.mark.parametrize("local_fields", [
    {"close_params": {"closeOrderList": [{"orderId": "LOCAL-ORDER", "closeOrderNotionalDelta": "1000000"}]}},
    {"tickers": [{"windCode": "LOCAL-CODE", "insShtDesc": "本地标的"}]},
    {"quote_content": "旧报价：本地期权类型，旧订单 LOCAL-QUOTE"},
    {"close_params": {"closeOrderList": [{"closeOrderType": "市价单"}]}},
], ids=["order-id", "ticker", "quoted-option-type", "confirmation-action"])
@pytest.mark.parametrize("backend_reply", [None, "  Java 平仓申请\r\n单号：CO-BACKEND\n请核对后确认平仓\n"])
async def test_close_card_comes_only_from_backend(local_fields, backend_reply):
    state = {"product_type": "option_close", "intent": "close_order_request", **local_fields}
    if backend_reply is not None:
        state.update(api_code=0, api_result=backend_reply)
    original = deepcopy(state)

    update = await render(state)

    if backend_reply is not None:
        assert update["reply_text"] == backend_reply
    else:
        assert update["reply_text"] == "交易指令执行结果待核对，请勿重复提交，请联系交易员或运营核查。"
        assert "LOCAL-" not in update["reply_text"]
        assert "确认平仓" not in update["reply_text"]
    assert state == original
