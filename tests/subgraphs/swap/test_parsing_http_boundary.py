"""固定 LLM/HTTP 外部响应，经过真实提取、GOATS 校验、DTO、提交与渲染。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.nodes.render import render
from app.subgraphs.swap import backend, place_order
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams
from app.tools.swap_client import SwapClientHttpx
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes

SHORTNAME = "11125测试短名（张天琪专用）"

REPORTS = [
    "新增指令：标的：NVDA方向：卖出股份数量：1453股建仓方式：pov跟量7%，"
    "不限价备注：根据市场成交量成交，标的：TSM方向：卖出股份数量：3071股"
    "建仓方式：pov跟量7%，不限价备注：根据市场成交量成交 " + SHORTNAME,
    "NVDA 卖出 1,453 股，均价 883.9758 TSM 卖出 3,071 股，均价 139.8888 " + SHORTNAME,
]


@pytest.mark.parametrize("case", [0, 1], ids=["report-pov-3071", "report-average-price"])
@pytest.mark.parametrize("reply,code", [
    ("-----场外收益互换详情-----\n单号：H-20260911-1234567890\n委托数量：【待补充】\n", 0),
    ("无持仓，无法卖出。\n请核对持仓。", 400),
    ("订单处理中，请勿重复提交", 0),
])
async def test_swap_request_and_backend_reply_survive_real_http_chain(
    monkeypatch, case, reply, code,
) -> None:
    raw = REPORTS[case]
    params = SwapPlaceOrderParams(orderList=[
        SwapOrderItem(
            placeOrderWindCode=symbol, placeOrderQuantity=quantity,
            placeOrderOrderDirection="SELL", placeOrderQuantityUnit="SHARE",
            placeOrderPriceType="MarketOrder" if case == 0 else None,
            placeOrderPrice=None if case == 0 else price,
            placeOrderAlgorithmType="POV" if case == 0 else "TWAP",
            placeOrderPovPercent=7 if case == 0 else None,
            placeOrderShortname=SHORTNAME,
        )
        for index, (symbol, quantity, price) in enumerate([
            ("NVDA", 1453, 883.9758), ("TSM", 3071, 139.8888),
        ])
    ])
    original = params.model_dump()
    queries, requests = [], []
    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/admin-api/swap-order/operate"
        assert request.method == "POST"
        requests.append(payload)
        return httpx.Response(200, json={
            "code": code, "data": reply if code == 0 else None, "msg": reply,
        })

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: SwapClientHttpx(
        base_url="http://swap.test", token="test-only", transport=transport, dry_run=False,
    ))
    state = {
        "raw_text": raw, "conversation_id": "parsing-regression", "message_id": "12345",
        "user_id": "test-user", "room_id": "test-room", "product_type": "swap",
        "swap_counterparties": [{"ctptyId": "1", "shortName": SHORTNAME}],
    }
    state["parsed_instruction"] = instruction_data("swap", "place_order_request", raw,
        orders=params.model_dump(exclude_none=True, exclude_unset=True)["orderList"])
    extracted = await place_order.swap_place_order(state)
    assert not extracted.get("error"), extracted.get("error")
    state.update(extracted)
    submitted = await run_request_nodes(place_order.swap_place_order_submit, state, "swap")
    assert not submitted.get("error"), submitted.get("error")
    state.update(submitted)
    rendered = await render(state)

    assert len(requests) == 1
    payload = requests[0]
    assert payload["rawContent"] == payload["messageContent"] == raw
    assert payload["type"] == "place_order_request"
    orders = payload["orderList"]
    assert [order["placeOrderWindCode"] for order in orders] == ["NVDA", "TSM"]
    assert [order["placeOrderQuantity"] for order in orders] == [1453, 3071]
    assert [order.get("placeOrderPrice") for order in orders] == (
        [None, None] if case == 0 else ["883.9758", "139.8888"]
    )
    assert [order["placeOrderShortname"] for order in orders] == [SHORTNAME, SHORTNAME]
    assert [order["placeOrderAlgorithmType"] for order in orders] == [
        "POV" if case == 0 else "TWAP",
    ] * 2
    assert [order.get("placeOrderPovPercent") for order in orders] == (
        [7, 7] if case == 0 else [None, None]
    )
    assert submitted["api_code"] == code
    assert submitted["api_result"] == rendered["reply_text"] == reply
    assert state["raw_text"] == raw
    assert params.model_dump() == original
    assert queries == []  # All instrument work is delegated through operate.


@pytest.mark.parametrize("raw,order,notional", [
    ("港股工商银行，限价15买一百万", {
        "placeOrderWindCode": "工商银行", "placeOrderTransactionType": "HK_STOCK",
        "placeOrderQuantityUnit": "AMOUNT", "placeOrderNotional": 1000000,
    }, "1000000"),
    ("GC2806合约，买入13手，市价", {
        "placeOrderWindCode": "GC2806合约", "placeOrderQuantityUnit": "HAND",
        "placeOrderQuantity": 13,
    }, None),
    ("中国铝业，限价14买入100w元", {
        "placeOrderWindCode": "中国铝业", "placeOrderQuantityUnit": "AMOUNT",
        "placeOrderNotional": 1000000, "placeOrderNotionalCurrency": "CNY",
    }, "1000000"),
    ("中国铝业，限价14买入100w元", {
        "placeOrderWindCode": "中国铝业", "placeOrderQuantityUnit": "AMOUNT",
        "placeOrderNotional": "100w", "placeOrderNotionalCurrency": "CNY",
    }, None),
], ids=["no-currency-from-market", "no-market-from-contract", "complete-amount", "dirty-amount-still-omitted"])
async def test_swap_explicit_fields_reach_java_without_defaults_or_unit_conversion(
    monkeypatch, raw: str, order: dict, notional: str | None,
) -> None:
    """真实来源、清洗和HTTP链保留稀疏提取，不补市场币种、不在代码中展开单位。"""
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        """捕获实际请求，仅替换后端响应，不绕过字段来源和类型清洗。"""
        assert request.url.path == "/admin-api/swap-order/operate"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "参数已接收"})

    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: SwapClientHttpx(
        base_url="http://swap.test", token="test-only",
        transport=httpx.MockTransport(handle), dry_run=False,
    ))
    state = {
        "raw_text": raw, "conversation_id": "explicit-fields", "message_id": "12345",
        "user_id": "test-user", "room_id": "test-room", "product_type": "swap",
        "parsed_instruction": instruction_data("swap", "place_order_request", raw, orders=[order]),
    }
    # 1. 沿真实准备节点保留提取值及原文证据。
    prepared = await place_order.swap_place_order(state)
    assert not prepared.get("error"), prepared.get("error")
    state.update(prepared)
    # 2. 沿父图同一清洗/提交路径检查最终wire值，不使用本地单位换算兜底。
    submitted = await run_request_nodes(place_order.swap_place_order_submit, state, "swap")
    assert not submitted.get("error"), submitted.get("error")
    assert len(requests) == 1
    actual = requests[0]["orderList"][0]
    assert requests[0]["rawContent"] == raw
    for field in ("placeOrderTransactionType", "placeOrderNotionalCurrency"):
        if field not in order:
            assert field not in actual
        else:
            assert actual[field] == order[field]
    if notional is None:
        assert "placeOrderNotional" not in actual
    else:
        assert str(actual["placeOrderNotional"]) == notional
