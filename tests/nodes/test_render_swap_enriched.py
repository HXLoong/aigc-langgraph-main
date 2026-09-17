"""互换回执不从原话或 ticker 元数据补写金额、币种、品种、对手和名称。

这些输入曾触发本地卡片增强。按当前后端透传契约，即使原话与回执字段
不同或后端字段待补充，render 也必须逐字保留后端结果。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.graph.state import AgentState, TickerCandidate
from app.nodes.render import render


@pytest.mark.parametrize(
    ("raw_text", "wind_code", "backend_reply"),
    [
        (
            "港股00700.HK 卖出200000元 380",
            "00700.HK",
            "委托金额: 199,500.00\n限定价格: 380",
        ),
        ("600519.SH 买入200万 限价1800", "600519.SH", "委托金额: 待补充"),
        ("美股AAPL 卖出50000USD 限价186", "AAPL.O", "币种: 待补充"),
        ("000001 买入200000", "000001.SZ", "标的代码: 000001.SZ"),
        ("港股00700.HK 卖出200000", "00700.HK", "交易品种: 待补充"),
        ("沪港通00388.HK 买入80000元 280", "00388.HK", "交易品种: 港股"),
        ("00700.HK 卖出 交易对手：对手A", "00700.HK", "交易对手: 对手B"),
        ("600519.SH 买入", "600519.SH", "标的名称: 后端证券名称"),
    ],
    ids=[
        "yuan-amount",
        "wan-amount",
        "explicit-currency",
        "no-default-currency",
        "trading-kind",
        "stock-connect",
        "counterparty",
        "ticker-name",
    ],
)
@pytest.mark.asyncio
async def test_local_context_never_enriches_backend_reply(
    raw_text: str, wind_code: str, backend_reply: str
) -> None:
    state: AgentState = {
        "product_type": "swap",
        "intent": "place_order_request",
        "raw_text": raw_text,
        "place_params": {
            "orderList": [{"placeOrderWindCode": wind_code}],
        },
        "tickers": [
            TickerCandidate(windCode=wind_code, insShtDesc="本地证券名称", from_goats=True)
        ],
        "api_result": backend_reply,
    }
    original = deepcopy(state)

    update = await render(state)

    assert update["reply_text"] == backend_reply
    assert state == original
