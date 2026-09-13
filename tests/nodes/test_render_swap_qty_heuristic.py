"""数量与价格由后端校验，render 不做交换、金额反算或回执修正。

保留旧启发式的四类输入，验证后端数量待补充和明确数量均原样透传，
同时确保原始订单参数不会被渲染过程修改。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.graph.state import AgentState
from app.nodes.render import render


@pytest.mark.parametrize(
    ("raw_text", "order"),
    [
        (
            "沪港通00388.HK 买入80000元 280",
            {"placeOrderWindCode": "00388.HK", "placeOrderQuantity": 280},
        ),
        (
            "深港通1357.HK 卖出78000HKD 限价19.50",
            {
                "placeOrderWindCode": "1357.HK",
                "placeOrderPrice": 19.50,
                "placeOrderPriceType": "LimitOrder",
            },
        ),
        (
            "600519.SH 买入200000元 18.12 100000股",
            {
                "placeOrderWindCode": "600519.SH",
                "placeOrderQuantity": 100000,
                "placeOrderPrice": 18.12,
            },
        ),
        ("600519.SH 买入50股", {"placeOrderWindCode": "600519.SH", "placeOrderQuantity": 50}),
    ],
    ids=["small-quantity-with-notional", "missing-quantity", "large-quantity", "no-notional"],
)
@pytest.mark.parametrize(
    "backend_reply", ["数量: 待补充\n限定价格: 待补充", "数量: 50股\n限定价格: 18.12"]
)
@pytest.mark.asyncio
async def test_render_never_recalculates_quantity_or_price(
    raw_text: str, order: dict[str, Any], backend_reply: str
) -> None:
    state: AgentState = {
        "product_type": "swap",
        "intent": "place_order_request",
        "raw_text": raw_text,
        "place_params": {"expected_action": "place", "orderList": [order]},
        "api_result": backend_reply,
    }
    original = deepcopy(state)

    update = await render(state)

    assert update["reply_text"] == backend_reply
    assert state == original
