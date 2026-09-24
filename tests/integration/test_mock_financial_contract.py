"""真实 OptionClient → ASGI mock → 引用解析，验证模拟生命周期的 wire 契约。"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.domain.confirmation import parse_confirmation
from app.subgraphs.close.reference_parser import parse_reference_message
from app.tools.option_client import FinancialOrderOpenApiSaveReqVO, OptionClientHttpx
from mock_api.server import app


@pytest.fixture
def context() -> dict[str, Any]:
    return {
        "conversationId": str(uuid4()),
        "roomId": str(uuid4()),
        "userId": "mock-contract-user",
        "messageId": 1,
        "messageContent": "契约测试",
        "rawContent": "契约测试",
    }


@pytest.fixture
def client() -> OptionClientHttpx:
    return OptionClientHttpx(
        base_url="http://mock",
        token="mock",
        transport=httpx.ASGITransport(app=app),
        dry_run=False,
    )


async def operate(
    client: OptionClientHttpx,
    context: dict[str, Any],
    intent: str,
    **params: Any,
) -> str:
    result = await client.operate(
        FinancialOrderOpenApiSaveReqVO.model_validate(
            {
                **context,
                "type": intent,
                **params,
            }
        )
    )
    assert result["code"] == 0, result
    assert isinstance(result["data"], str)
    return result["data"]


def ids(card: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf"{prefix}-\d{{8}}-[A-Z0-9]+", card)))


async def close_request(
    client: OptionClientHttpx,
    context: dict[str, Any],
    items: list[dict[str, Any]],
) -> str:
    return await operate(
        client,
        context,
        "close_order_request",
        closeOrderReqVO={
            "closeOrderList": items,
        },
    )


async def test_close_wire_fields_survive_card_and_reference_parsing(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    card = await close_request(
        client,
        context,
        [
            {
                "internalTradeId": "OPT-LYAFT20260001",
                "closeOrderNotionalDelta": "2500000",
                "closeOrderType": "限价单",
                "closeOrderPrice": "12.34",
            },
            {
                "internalTradeId": "OPT-SZZSCF20260004",
                "closeOrderNotionalDelta": "3000000",
                "closeOrderType": "TWAP",
                "closeOrderAlgoStartTime": "13:00",
                "closeOrderAlgoEndTime": "14:00",
            },
        ],
    )
    assert "合约编号：OPT-LYAFT20260001" in card
    assert "合约编号：OPT-SZZSCF20260004" in card
    assert "平仓名义本金：2,500,000" in card
    assert "平仓价格方式：限价单" in card and "12.34" in card
    assert "13:00" in card and "14:00" in card
    order_ids = ids(card, "CO")
    assert len(order_ids) == 2
    parsed = parse_reference_message(card, "序号2，确认平仓")
    assert parsed["messageType"] == "close_result"
    assert [item["orderId"] for item in parsed["successOrders"]] == order_ids
    assert [item["contractId"] for item in parsed["holdingMap"]] == [
        "OPT-LYAFT20260001",
        "OPT-SZZSCF20260004",
    ]
    confirmation = parse_confirmation("序号2，确认平仓", card, product="close", action="close")
    assert not confirmation.error
    assert confirmation.order_ids == (order_ids[1],)
    query = await client.query_close_orders(order_ids=order_ids, room_id=context["roomId"])
    assert [row["orderId"] for row in query["data"]] == order_ids
    assert query["data"][0]["contractCode"] == "OPT-LYAFT20260001"
    assert query["data"][0]["availableNotional"] == 10000000
    assert query["data"][0]["notional"] == 10000000


async def test_close_incomplete_parameters_can_be_completed_on_same_order(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    first = await close_request(client, context, [{"internalTradeId": "OPT-LYAFT20260001"}])
    assert "平仓名义本金：【待补充】" in first
    assert "平仓价格方式：【待补充】" in first
    (order_id,) = ids(first, "CO")
    parsed = parse_reference_message(first, "200万，市价平仓")
    assert parsed["singleHoldingCandidateOrderId"] == order_id
    assert parsed["successOrders"] == []
    second = await close_request(
        client,
        context,
        [
            {
                "orderId": order_id,
                "closeOrderNotionalDelta": "2000000",
                "closeOrderType": "市价单",
            }
        ],
    )
    assert ids(second, "CO") == [order_id]
    assert "合约编号：OPT-LYAFT20260001" in second
    assert "平仓名义本金：2,000,000" in second
    assert "【待补充】" not in second


async def test_close_lifecycle_keeps_reference_ids_and_query_state(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    card = await close_request(
        client,
        context,
        [
            {
                "internalTradeId": "OPT-LYAFT20260001",
                "closeOrderNotionalDelta": "2000000",
                "closeOrderType": "市价单",
            }
        ],
    )
    (order_id,) = ids(card, "CO")
    for intent, field, command, action in [
        ("close_order_confirm", "confirmOrderNoList", "确认平仓", "close"),
        ("close_order_cancel_request", "cancelOrderNoList", "确认撤单", "cancel"),
        ("close_order_cancel_confirm", "confirmCancelOrderNoList", "确认撤单", "cancel"),
    ]:
        card = await operate(client, context, intent, closeOrderReqVO={field: [order_id]})
        assert ids(card, "CO") == [order_id]
        assert "合约编号：OPT-LYAFT20260001" in card
        assert parse_confirmation(command, card, product="close", action=action).order_ids == (
            order_id,
        )
    queried = await operate(
        client,
        context,
        "close_order_order_query",
        closeOrderReqVO={
            "queryOrderNoList": [order_id],
        },
    )
    assert ids(queried, "CO") == [order_id]
    assert "已撤单" in queried
    assert "已成交" not in queried


async def test_option_lifecycle_retains_q_ids_and_partial_selection(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    inquiry = await operate(
        client,
        context,
        "new_inquiry",
        orderList=[
            {
                "stockCode": "600519.SH",
                "optionType": "欧式看涨",
                "tenor": "1M",
                "strikePercentage": "80",
            },
            {"stockCode": "000858.SZ", "optionType": "欧式看涨", "tenor": "3M"},
        ],
    )
    order_ids = ids(inquiry, "Q")
    assert len(order_ids) == 2
    assert all(re.fullmatch(r"Q-\d{8}-\d{10}", order_id) for order_id in order_ids)
    placed = await operate(
        client,
        context,
        "place_order_from_quote",
        orderList=[
            {
                "orderId": order_id,
                "notionalAmount": "2000000",
                "orderType": "市价单",
                "shortName": "临沂阿凡提",
            }
            for order_id in order_ids
        ],
    )
    assert ids(placed, "Q") == order_ids
    assert "600519.SH" in placed and "000858.SZ" in placed
    assert "80%" in placed and "3M" in placed
    selected = parse_confirmation("序号2，确认下单", placed, product="option")
    assert not selected.error
    assert selected.order_ids == (order_ids[1],)
    card = placed
    for intent in ["confirm_order", "request_cancel_order", "confirm_cancel_order"]:
        card = await operate(client, context, intent, orderList=[{"orderId": order_ids[1]}])
        assert ids(card, "Q") == [order_ids[1]]
        assert "已收到您的" in card
    queried = await operate(
        client,
        context,
        "query_order_status",
        orderList=[{"orderId": order_id} for order_id in order_ids],
    )
    assert ids(queried, "Q") == order_ids
    assert "待确认" in queried and "已撤单" in queried
    assert "已成交" not in queried


@pytest.mark.parametrize("different", ["conversationId", "roomId", "userId"])
async def test_dynamic_option_orders_are_isolated(
    client: OptionClientHttpx, context: dict[str, Any], different: str
) -> None:
    card = await operate(client, context, "new_inquiry", orderList=[{"stockCode": "600519.SH"}])
    (order_id,) = ids(card, "Q")
    alien = {**context, different: str(uuid4())}
    for intent in [
        "place_order_from_quote",
        "confirm_order",
        "request_cancel_order",
        "confirm_cancel_order",
        "query_order_status",
    ]:
        result = await operate(client, alien, intent, orderList=[{"orderId": order_id}])
        assert "订单不存在" in result
        assert "已收到您的" not in result


async def test_dynamic_close_orders_cannot_be_queried_from_another_room(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    card = await close_request(client, context, [{"internalTradeId": "OPT-LYAFT20260001"}])
    (order_id,) = ids(card, "CO")
    for room in [None, "other-room"]:
        response = await client.query_close_orders(order_ids=[order_id], room_id=room)
        assert response["data"] == []
    for different in ["conversationId", "roomId", "userId"]:
        result = await operate(
            client,
            {**context, different: str(uuid4())},
            "close_order_confirm",
            closeOrderReqVO={"confirmOrderNoList": [order_id]},
        )
        assert "订单不存在" in result
        assert "已收到您的" not in result


async def test_unknown_contract_and_order_are_not_fabricated(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    card = await close_request(
        client,
        context,
        [
            {
                "internalTradeId": "OPT-UNKNOWN",
                "closeOrderNotionalDelta": "2000000",
                "closeOrderType": "市价单",
            }
        ],
    )
    assert "合约编号不存在" in card
    assert not ids(card, "CO")
    result = await operate(
        client,
        context,
        "query_order_status",
        orderList=[
            {"orderId": "Q-20260923-9999999999"},
        ],
    )
    assert "订单不存在" in result
    assert "已成交" not in result
    result = await operate(
        client,
        context,
        "close_order_order_query",
        closeOrderReqVO={
            "queryOrderNoList": ["CO-20260923-FFFFFFFF"],
        },
    )
    assert "订单不存在" in result
    assert "已成交" not in result


async def test_incomplete_orders_cannot_be_confirmed(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    card = await close_request(client, context, [{"internalTradeId": "OPT-LYAFT20260001"}])
    result = await operate(
        client,
        context,
        "close_order_confirm",
        closeOrderReqVO={
            "confirmOrderNoList": ids(card, "CO"),
        },
    )
    assert "已收到您的下单请求" not in result
    assert "参数需要完善" in result
    card = await operate(client, context, "new_inquiry", orderList=[{"stockCode": "600519.SH"}])
    result = await operate(
        client,
        context,
        "confirm_order",
        orderList=[{"orderId": order_id} for order_id in ids(card, "Q")],
    )
    assert "已收到您的下单请求" not in result
    assert "参数需要完善" in result


async def test_explicit_lifecycle_holding_seed_is_queryable(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    card = await operate(client, context, "close_order_query")
    parsed = parse_reference_message(card, "序号1平仓")
    assert parsed["holdingMap"][0]["contractId"] == "OPT-AAAA1"
    order_id = parsed["holdingMap"][0]["orderId"]
    query = await client.query_close_orders(order_ids=[order_id], room_id=context["roomId"])
    assert query["data"][0]["contractCode"] == "OPT-AAAA1"
    card = await close_request(
        client,
        context,
        [
            {
                "orderId": order_id,
                "closeOrderNotionalDelta": "2000000",
                "closeOrderType": "市价单",
            }
        ],
    )
    assert ids(card, "CO") == [order_id]
    assert "合约编号：OPT-AAAA1" in card
    assert "平仓名义本金：2,000,000" in card


@pytest.mark.parametrize(
    "item",
    [
        {"notionalAmount": "2000000", "orderType": "市价单", "shortName": "临沂阿凡提"},
        {
            "stockCode": "600519.SH",
            "notionalAmount": "-2000000",
            "orderType": "市价单",
            "shortName": "临沂阿凡提",
        },
    ],
)
async def test_option_missing_target_or_invalid_amount_is_not_confirmable(
    client: OptionClientHttpx, context: dict[str, Any], item: dict[str, Any]
) -> None:
    card = await operate(client, context, "place_order_from_quote", orderList=[item])
    result = await operate(
        client,
        context,
        "confirm_order",
        orderList=[{"orderId": order_id} for order_id in ids(card, "Q")],
    )
    assert "已收到您的下单请求" not in result


@pytest.mark.parametrize(
    "item",
    [
        {"closeOrderNotionalDelta": "-2000000", "closeOrderType": "市价单"},
        {"closeOrderNotionalDelta": "2000000", "closeOrderType": "限价单"},
        {"closeOrderNotionalDelta": "2000000", "closeOrderType": "TWAP"},
        {"closeOrderNotionalDelta": "2000000", "closeOrderType": "unsupported"},
    ],
)
async def test_close_invalid_or_incomplete_execution_is_not_confirmable(
    client: OptionClientHttpx, context: dict[str, Any], item: dict[str, Any]
) -> None:
    card = await close_request(client, context, [{"internalTradeId": "OPT-LYAFT20260001", **item}])
    assert parse_reference_message(card, "确认平仓")["successOrders"] == []
    result = await operate(
        client,
        context,
        "close_order_confirm",
        closeOrderReqVO={
            "confirmOrderNoList": ids(card, "CO"),
        },
    )
    assert "已收到您的下单请求" not in result


async def test_contract_lookup_does_not_bind_existing_close_orders(
    client: OptionClientHttpx, context: dict[str, Any]
) -> None:
    card = await close_request(client, context, [{"internalTradeId": "OPT-LYAFT20260001"}])
    (order_id,) = ids(card, "CO")
    result = await client.query_close_orders(
        contract_codes=["OPT-LYAFT20260001"],
        room_id=context["roomId"],
        message_id=1,
    )
    expected_contract = {
        "orderId": None,
        "contractCode": "OPT-LYAFT20260001",
        "availableNotional": 10000000,
        "notional": 10000000,
    }
    assert result["data"] == [expected_contract]
    combined = await client.query_close_orders(
        order_ids=[order_id],
        contract_codes=["OPT-LYAFT20260001"],
        room_id=context["roomId"],
        message_id=1,
    )
    assert combined["data"] == [{**expected_contract, "orderId": order_id}, expected_contract]
    empty = await client.query_close_orders(room_id=context["roomId"], message_id=1)
    assert empty["data"] == []


@pytest.mark.parametrize('expression,code', [('宁德时代', '300750.SZ'), ('茅台', '600519.SH')])
async def test_mock_inquiry_accepts_raw_instrument_name_in_stock_code(client, context, expression, code):
    card = await operate(client, context, 'new_inquiry', orderList=[{'stockCode': expression}])
    assert code in card and 'mock' in card


async def test_mock_inquiry_does_not_guess_unknown_instrument(client, context):
    response = await client.operate(FinancialOrderOpenApiSaveReqVO.model_validate({
        **context, 'type': 'new_inquiry', 'orderList': [{'stockCode': '未知标的测试表达'}],
    }))
    assert response['code'] == 400
