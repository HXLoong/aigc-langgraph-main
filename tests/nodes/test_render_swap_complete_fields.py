"""互换卡片字段由后端决定；本地参数完整度不影响回执透传。

契约见 docs/api-contracts/java-backend.md §3.1。旧版要求 render 补齐固定
模板的断言已失效；保留最少、完整和空订单三个场景，防止恢复本地拼卡。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.graph.state import AgentState, TickerCandidate
from app.nodes.render import render


@pytest.mark.parametrize(
    "order",
    [
        {"placeOrderWindCode": "000001.SZ", "placeOrderOrderDirection": "BUY"},
        {
            "placeOrderWindCode": "600519.SH",
            "placeOrderOrderDirection": "BUY",
            "placeOrderQuantity": 1000,
            "placeOrderPriceType": "LimitOrder",
            "placeOrderPrice": 1800.5,
            "placeOrderAlgorithmType": "POV",
            "placeOrderPovPercent": 25,
            "placeOrderStartTime": "14:00",
            "placeOrderEndTime": "15:00",
        },
        {},
    ],
    ids=["minimal-order", "complete-order", "empty-order"],
)
@pytest.mark.parametrize("backend_reply", [None, "  标的代码: 600519.SH\r\n数量: 待补充\n"])
@pytest.mark.asyncio
async def test_order_fields_never_rebuild_backend_card(
    order: dict[str, Any], backend_reply: str | None
) -> None:
    state: AgentState = {
        "product_type": "swap",
        "intent": "place_order_request",
        "place_params": {"orderList": [order]},
        "tickers": [TickerCandidate(windCode="600519.SH", insShtDesc="贵州茅台", from_goats=True)],
        "api_result": backend_reply,
    }
    original = deepcopy(state)

    update = await render(state)

    assert update["reply_text"] == (
        backend_reply
        if backend_reply is not None
        else "互换服务未返回有效结果，本次未生成业务回执，请稍后重试或联系交易员。"
    )
    assert state == original
