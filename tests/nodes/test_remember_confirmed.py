"""remember_confirmed_params：一轮写类操作成功后，把订单号记进 ConversationMemory（ADR 0024 D4）。"""
from __future__ import annotations

import pytest

from app.nodes.remember_confirmed import remember_confirmed_params


@pytest.mark.asyncio
async def test_swap_place_success_records_order_ids_from_order_list() -> None:
    update = await remember_confirmed_params({
        "product_type": "swap", "intent": "place_order_request", "expected_action": "place",
        "message_id": 42, "api_code": 0, "api_result": "下单成功",
        "place_params": {"orderList": [{"orderId": "H-20260917-0000000001"}, {"orderId": "H-20260917-0000000002"}]},
    })
    memory = update["last_confirmed_params"]
    assert memory["order_ids"] == ["H-20260917-0000000001", "H-20260917-0000000002"]
    assert (memory["product_type"], memory["intent"], memory["expected_action"], memory["message_id"]) == (
        "swap", "place_order_request", "place", 42,
    )


@pytest.mark.asyncio
async def test_option_inquiry_success_reads_order_ids_from_backend_card() -> None:
    update = await remember_confirmed_params({
        "product_type": "option", "intent": "new_inquiry", "expected_action": "inquiry",
        "message_id": 7, "api_code": 0,
        "api_result": "-----场外期权询价详情-----\n单号：Q-20260917-AB12CD\n期限：1M",
        "place_params": {"orderList": [{"stockCode": "600519.SH"}]},
    })
    assert update["last_confirmed_params"]["order_ids"] == ["Q-20260917-AB12CD"]


@pytest.mark.asyncio
async def test_close_success_reads_co_ids() -> None:
    update = await remember_confirmed_params({
        "product_type": "option_close", "intent": "close_order_request", "expected_action": "close",
        "message_id": 9, "api_code": 0,
        "api_result": "期权平仓订单CO-20260304-4FE9C941（OPT-1）：已受理",
    })
    assert update["last_confirmed_params"]["order_ids"] == ["CO-20260304-4FE9C941"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [
    {"product_type": "swap", "expected_action": "place", "api_code": 500, "api_result": "拒绝",
     "place_params": {"orderList": [{"orderId": "H-20260917-0000000001"}]}},
    {"product_type": "swap", "expected_action": "cancel", "api_code": 0, "api_result": "H-20260917-0000000001 已撤"},
    {"product_type": "swap", "expected_action": "place", "api_code": 0, "api_result": "下单成功", "place_params": {"orderList": [{}]}},
    {"product_type": "swap", "intent": "query_order_status", "api_code": 0, "api_result": "H-20260917-0000000001"},
])
async def test_no_memory_update_when_not_a_successful_write_with_ids(state: dict) -> None:
    update = await remember_confirmed_params(state)
    assert "last_confirmed_params" not in update, "不满足条件时不得覆盖既有记忆"


@pytest.mark.asyncio
async def test_error_turn_keeps_previous_memory() -> None:
    from app.graph.state import ErrorInfo

    update = await remember_confirmed_params({
        "product_type": "swap", "expected_action": "place", "api_code": 0, "api_result": "x",
        "error": ErrorInfo(node="n", type="T", message="m"),
        "place_params": {"orderList": [{"orderId": "H-20260917-0000000001"}]},
        "last_confirmed_params": {"product_type": "swap", "order_ids": ["H-1"]},
    })
    assert "last_confirmed_params" not in update
