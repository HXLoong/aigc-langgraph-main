"""后端 mock 接口完整测试（pytest，无需启动 server，用 ASGITransport 内存调用）。

覆盖 10 个 /admin-api/* 端点：
- swap-order/operate × 7 type 分发 + 入参校验
- swap-order/get / get-conversation-orders
- financial-orders/operate × 16 type 分发 + 入参校验
- financial-orders/query-close-orders
- integration/securities-instrument/select（GET + POST + 多关键词）
- counterparty/info/list + instrument-inference-prompt
- business/config/bot/name/list
- openapi/xbot/message/set-intent

同时 smoke 测试入参缺失时 422 校验。
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mock_api.server import app

BACKEND_BASE = "http://test"
BOT_CTX = {
    "messageId": 1001,
    "messageContent": "测试消息",
    "rawContent": "测试消息",
    "userId": "u-1",
    "roomId": "r-1",
}


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=BACKEND_BASE, timeout=10.0
    ) as c:
        yield c


def _payload(type_: str, **extra: Any) -> dict[str, Any]:
    return {"type": type_, **BOT_CTX, **extra}


# ============================================================
# /admin-api/swap-order/operate
# ============================================================


@pytest.mark.parametrize(
    "type_,expect_keyword",
    [
        ("place_order_request", "下单确认"),
        ("confirm_order", "确认下单"),
        ("cancel_order_request", "撤单请求"),
        ("confirm_cancel_order", "确认撤单"),
        ("confirm_modify_order", "确认改单"),
        ("query_order_status", "订单状态查询"),
        ("unknown_intent", "未识别"),
    ],
)
@pytest.mark.asyncio
async def test_swap_operate_dispatches_all_7_intents(
    client: httpx.AsyncClient, type_: str, expect_keyword: str
) -> None:
    r = await client.post(
        "/admin-api/swap-order/operate",
        json=_payload(type_, orderList=[]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    assert expect_keyword in body["data"]


@pytest.mark.asyncio
async def test_swap_operate_modify_when_orderId_present(
    client: httpx.AsyncClient,
) -> None:
    """orderList 含 orderId → 走改单路径。"""
    r = await client.post(
        "/admin-api/swap-order/operate",
        json=_payload(
            "place_order_request",
            orderList=[
                {
                    "orderId": "H-20260510-00000001",
                    "placeOrderWindCode": "0700.HK",
                    "placeOrderQuantity": 1000,
                    "placeOrderOrderDirection": "BUY",
                    "placeOrderPriceType": "LimitOrder",
                    "placeOrderPrice": "472.00",
                }
            ],
        ),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "改单确认" in data
    assert "H-20260510-00000001" in data
    assert "腾讯控股" in data  # 触发标的解析


@pytest.mark.asyncio
async def test_swap_operate_validation_error_when_missing_required(
    client: httpx.AsyncClient,
) -> None:
    """缺 messageId / rawContent → 422。"""
    r = await client.post(
        "/admin-api/swap-order/operate",
        json={"type": "place_order_request"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_swap_operate_invalid_type_rejected(
    client: httpx.AsyncClient,
) -> None:
    """type 不在 7 个枚举内 → 422。"""
    r = await client.post(
        "/admin-api/swap-order/operate",
        json=_payload("garbage_intent"),
    )
    assert r.status_code == 422


# ============================================================
# /admin-api/swap-order/get + get-conversation-orders
# ============================================================


@pytest.mark.asyncio
async def test_swap_order_get_returns_order_detail(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get(
        "/admin-api/swap-order/get",
        params={"orderId": "H-20260510-00000001"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["orderId"] == "H-20260510-00000001"
    assert data["windCode"] == "0700.HK"
    assert data["orderStatus"] == "PARTIALLY_FILLED"


@pytest.mark.asyncio
async def test_swap_order_get_missing_param_422(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get("/admin-api/swap-order/get")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_swap_get_conversation_orders(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/admin-api/swap-order/get-conversation-orders",
        json={"conversationId": "conv-001"},
    )
    assert r.status_code == 200
    orders = r.json()["data"]
    assert len(orders) == 1
    assert orders[0]["conversationId"] == "conv-001"


# ============================================================
# /admin-api/financial-orders/operate
# ============================================================


_FINANCIAL_INTENTS_AND_KEYWORDS = [
    ("new_inquiry", "询价详情"),
    ("place_order_from_quote", "下单确认"),
    ("request_modify_order", "改单确认"),
    ("confirm_order", "确认下单"),
    ("cancel_order_request", "撤单请求"),
    ("request_cancel_order", "撤单请求"),
    ("confirm_cancel_order", "确认撤单"),
    ("confirm_modify_order", "确认改单"),
    ("query_order_status", "订单状态"),
    ("close_order_query", "持仓详情"),
    ("close_order_request", "平仓申请"),
    ("close_order_confirm", "平仓确认下单"),
    ("close_order_cancel_request", "平仓撤单请求"),
    ("close_order_cancel_confirm", "平仓确认撤单"),
    ("close_order_order_query", "平仓订单查询"),
    ("unknown_intent", "未识别"),
]


@pytest.mark.parametrize("type_,expect_keyword", _FINANCIAL_INTENTS_AND_KEYWORDS)
@pytest.mark.asyncio
async def test_financial_operate_dispatches_all_16_intents(
    client: httpx.AsyncClient, type_: str, expect_keyword: str
) -> None:
    r = await client.post(
        "/admin-api/financial-orders/operate",
        json=_payload(type_, orderList=[]),
    )
    assert r.status_code == 200, (type_, r.text)
    body = r.json()
    assert body["code"] == 0
    assert expect_keyword in body["data"], (type_, body["data"][:200])


@pytest.mark.asyncio
async def test_financial_operate_inquiry_resolves_stock_name(
    client: httpx.AsyncClient,
) -> None:
    """new_inquiry orderList 含 stockCode=0700.HK → 渲染卡片含 腾讯控股。"""
    r = await client.post(
        "/admin-api/financial-orders/operate",
        json=_payload(
            "new_inquiry",
            orderList=[
                {
                    "stockCode": "0700.HK",
                    "optionType": "欧式看涨",
                    "tenor": "1M",
                    "strikePercentage": 100,
                }
            ],
        ),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "0700.HK" in data
    assert "腾讯控股" in data
    assert "1M" in data


@pytest.mark.asyncio
async def test_financial_operate_close_request_renders_contract(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post(
        "/admin-api/financial-orders/operate",
        json=_payload(
            "close_order_request",
            closeOrderReqVO={
                "closeOrderList": [
                    {
                        "internalTradeId": "OPT-LYAFT20260001",
                        "closeOrderNotionalDelta": "5000000",
                        "closeOrderType": "市价单",
                    }
                ]
            },
        ),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "OPT-LYAFT20260001" in data
    assert "川能动力" in data  # underlying 关联
    assert "5,000,000" in data


@pytest.mark.asyncio
async def test_financial_operate_validation_error(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post(
        "/admin-api/financial-orders/operate",
        json={"type": "new_inquiry"},  # 缺机器人上下文
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_financial_operate_invalid_type_rejected(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post(
        "/admin-api/financial-orders/operate",
        json=_payload("garbage_intent"),
    )
    assert r.status_code == 422


# ============================================================
# /admin-api/financial-orders/query-close-orders
# ============================================================


@pytest.mark.asyncio
async def test_query_close_orders_by_order_ids(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/admin-api/financial-orders/query-close-orders",
        json={"orderIds": ["CO-20260506-85AB8526", "CO-20260506-7C8DEF06"]},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    ids = {d["orderId"] for d in data}
    assert ids == {"CO-20260506-85AB8526", "CO-20260506-7C8DEF06"}
    assert all("availableNotional" in d and "notional" in d for d in data)


@pytest.mark.asyncio
async def test_query_close_orders_by_contract_codes(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post(
        "/admin-api/financial-orders/query-close-orders",
        json={"contractCodes": ["OPT-LYAFT20260001"]},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["contractCode"] == "OPT-LYAFT20260001"
    assert data[0]["orderId"] is None


@pytest.mark.asyncio
async def test_query_close_orders_empty_returns_empty(
    client: httpx.AsyncClient,
) -> None:
    """无订单号和合约编号时，真实 Java 不查询任何数据。"""
    r = await client.post(
        "/admin-api/financial-orders/query-close-orders",
        json={},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data == []


# ============================================================
# /admin-api/integration/securities-instrument/select
# ============================================================


@pytest.mark.asyncio
async def test_securities_select_exact_match(client: httpx.AsyncClient) -> None:
    r = await client.request(
        "GET",
        "/admin-api/integration/securities-instrument/select",
        json={"keywordItems": [{"keyword": "0700.HK", "isFull": True}]},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["windCode"] == "0700.HK"
    assert data[0]["insShtDesc"] == "腾讯控股"
    assert data[0]["relevanceScore"] == 0


@pytest.mark.asyncio
async def test_securities_select_fuzzy_match(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/admin-api/integration/securities-instrument/select",
        json={"keywordItems": [{"keyword": "茅台", "isFull": False}]},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert any(item["windCode"] == "600519.SH" for item in data)


@pytest.mark.asyncio
async def test_securities_select_multi_keyword_dedup(
    client: httpx.AsyncClient,
) -> None:
    r = await client.post(
        "/admin-api/integration/securities-instrument/select",
        json={
            "keywordItems": [
                {"keyword": "茅台", "isFull": False},
                {"keyword": "腾讯", "isFull": False},
                {"keyword": "TSLA", "isFull": False},
            ]
        },
    )
    assert r.status_code == 200
    data = r.json()["data"]
    codes = {d["windCode"] for d in data}
    assert "600519.SH" in codes
    assert "0700.HK" in codes
    assert "TSLA.O" in codes
    # relevanceScore 升序
    scores = [d["relevanceScore"] for d in data]
    assert scores == sorted(scores)


# ============================================================
# /admin-api/counterparty/info/list + instrument-inference-prompt
# ============================================================


@pytest.mark.asyncio
async def test_counterparty_list_returns_4_with_transaction_types(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get(
        "/admin-api/counterparty/info/list",
        params={"type": "TRS", "roomId": "room-001"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 4
    for cp in data:
        assert "ctptyId" in cp
        assert "shortName" in cp
        assert "transactionTypeList" in cp
        assert isinstance(cp["transactionTypeList"], list)


@pytest.mark.asyncio
async def test_counterparty_list_missing_required_422(
    client: httpx.AsyncClient,
) -> None:
    """type / roomId 必填，缺失 → 422。"""
    r = await client.get(
        "/admin-api/counterparty/info/list",
        params={"type": ""},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_instrument_inference_prompt_returns_string(
    client: httpx.AsyncClient,
) -> None:
    r = await client.get(
        "/admin-api/counterparty/info/instrument-inference-prompt"
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data, str)
    assert "标的代码" in data


# ============================================================
# /admin-api/business/config/bot/name/list + set-intent
# ============================================================


@pytest.mark.asyncio
async def test_bot_name_list_returns_json_string(
    client: httpx.AsyncClient,
) -> None:
    """data 字段是 JSON 字符串（与真实后端一致）。"""
    r = await client.post("/admin-api/business/config/bot/name/list")
    assert r.status_code == 200
    data = r.json()["data"]
    assert isinstance(data, str)
    parsed = json.loads(data)
    assert isinstance(parsed, list)
    assert "otc-agent" in parsed


@pytest.mark.asyncio
async def test_set_intent_returns_ok(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/admin-api/openapi/xbot/message/set-intent",
        json={"messageId": 999, "intent": "place_order_request"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"] is None


# ============================================================
# 整体路由清单（健康检查）
# ============================================================


@pytest.mark.asyncio
async def test_root_lists_all_admin_endpoints(client: httpx.AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    admin_routes = [r for r in body["routes"] if "/admin-api" in r]
    assert len(admin_routes) >= 10
