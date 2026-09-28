"""render 必须逐字透传后端回执，不做任何本地加工。

本文件合并原先按「字段完整度 / 本地增强 / 数量启发式 / 后端拒绝」拆分的四个文件——
四者验证的是同一条不变量：render 不改写 Java 生成的业务卡片或拒绝文案。

- 互换卡片字段由后端决定；本地参数完整度不影响回执透传（契约 docs/api-contracts/java-backend.md §3.1）
- 互换回执不从原话或 ticker 元数据补写金额、币种、品种、对手和名称
- 数量与价格由后端校验，render 不做交换、金额反算或回执修正
- 期权后端业务回复由后端全权生成，render 不增删内容

缺少后端回执时统一为"待核对"文案（ADR 0026 D3）。
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from app.graph.state import AgentState, TickerCandidate
from app.nodes.render import render
from app.tools.receipts import UNCERTAIN_REPLY

# ============================================================
# 互换 · 本地参数完整度不影响透传
# ============================================================


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
        backend_reply if backend_reply is not None else UNCERTAIN_REPLY
    )
    assert state == original


# ============================================================
# 互换 · 不从原话或 ticker 元数据补写字段
# ============================================================


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


# ============================================================
# 互换 · 不重算数量与价格
# ============================================================


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
        "place_params": {"orderList": [order]},
        "api_result": backend_reply,
    }
    original = deepcopy(state)

    update = await render(state)

    assert update["reply_text"] == backend_reply
    assert state == original


# ============================================================
# 期权 · 后端回复原样透传
# ============================================================


@pytest.mark.asyncio
class TestBackendReplyPassthrough:
    async def test_pool_rejection_is_not_modified(self) -> None:
        ticker = SimpleNamespace(
            wind_code="399006.SZ", ins_sht_desc="创业板指", from_goats=True
        )
        rejection = "399006.SZ不在标的池内，请联系对口销售或交易员。"
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": rejection,
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == rejection

    async def test_quote_not_exist_is_not_modified(self) -> None:
        ticker = SimpleNamespace(
            wind_code="000016.SH", ins_sht_desc="上证50", from_goats=True
        )
        rejection = "000016.SH报价不存在，请联系对口销售或交易员。"
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": rejection,
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == rejection

    async def test_no_tickers_no_augment(self) -> None:
        """无 tickers → 不附加（无识别可声明）。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [],
            "api_result": "标的不在池内。",
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == "标的不在池内。"

    async def test_normal_api_result_not_augmented(self) -> None:
        """正常的 api_result（含订单详情）不该被附加。"""
        ticker = SimpleNamespace(
            wind_code="600519.SH", ins_sht_desc="贵州茅台", from_goats=True
        )
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [ticker],
            "api_result": "-----场外期权询价详情-----\n单号：Q-001\n标的：600519.SH",
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == state["api_result"]

    async def test_dict_ticker_also_works(self) -> None:
        """ticker 是 dict 形式（state 序列化后）也能正确读字段。"""
        state: dict = {
            "product_type": "option",
            "intent": "new_inquiry",
            "tickers": [{"windCode": "399006.SZ", "insShtDesc": "创业板指"}],
            "api_result": "399006.SZ不在标的池内。",
        }
        update = await render(state)  # type: ignore[arg-type]
        assert update["reply_text"] == state["api_result"]
