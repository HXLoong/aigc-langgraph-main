"""路由节点单元测试。"""
from __future__ import annotations

import pytest

from app.nodes.route import route_product, route_product_condition
from app.state import make_initial_state


@pytest.mark.asyncio
async def test_route_close_by_order_number():
    """命中平仓单号格式 → option_close。"""
    wx = {
        "conversation_id": "c1",
        "message_id": "m1",
        "room_id": "r1",
        "user_id": "u1",
        "guid": "",
        "raw_content": "请帮我平 CO-20260304-4FE9C941",
    }
    state = make_initial_state(wx)
    result = await route_product(state)
    assert result["product_type"] == "option_close"


@pytest.mark.asyncio
async def test_route_close_by_contract_number():
    """合约编号也识别为 close。"""
    wx = {
        "conversation_id": "c1",
        "message_id": "m1",
        "room_id": "r1",
        "user_id": "u1",
        "guid": "",
        "raw_content": "OPTG-SZZSCF20250030 平仓",
    }
    state = make_initial_state(wx)
    result = await route_product(state)
    assert result["product_type"] == "option_close"


@pytest.mark.asyncio
async def test_route_swap_by_keyword():
    wx = {
        "conversation_id": "c1", "message_id": "m1", "room_id": "r1",
        "user_id": "u1", "guid": "",
        "raw_content": "做一笔 TRS 互换，跟量 100%",
    }
    state = make_initial_state(wx)
    result = await route_product(state)
    assert result["product_type"] == "swap"


@pytest.mark.asyncio
async def test_route_swap_by_attachment():
    """有图片/Excel 附件 → 互换。"""
    wx = {
        "conversation_id": "c1", "message_id": "m1", "room_id": "r1",
        "user_id": "u1", "guid": "",
        "raw_content": "这是订单",
        "attachments": [{"url": "http://example.com/x.xlsx", "type": "excel"}],
    }
    state = make_initial_state(wx)
    result = await route_product(state)
    assert result["product_type"] == "swap"


@pytest.mark.asyncio
async def test_route_option_by_keyword():
    wx = {
        "conversation_id": "c1", "message_id": "m1", "room_id": "r1",
        "user_id": "u1", "guid": "",
        "raw_content": "茅台雪球报价",
    }
    state = make_initial_state(wx)
    result = await route_product(state)
    assert result["product_type"] == "option"


@pytest.mark.asyncio
async def test_route_unknown():
    wx = {
        "conversation_id": "c1", "message_id": "m1", "room_id": "r1",
        "user_id": "u1", "guid": "",
        "raw_content": "今天天气不错",
    }
    state = make_initial_state(wx)
    result = await route_product(state)
    assert result["product_type"] == "unknown"


@pytest.mark.asyncio
async def test_route_priority_close_over_swap():
    """附件 + 平仓单号 → close 优先（符合业务语义）。"""
    wx = {
        "conversation_id": "c1", "message_id": "m1", "room_id": "r1",
        "user_id": "u1", "guid": "",
        "raw_content": "平 CO-20260304-4FE9C941",
        "attachments": [{"url": "http://example.com/x.xlsx"}],
    }
    state = make_initial_state(wx)
    result = await route_product(state)
    assert result["product_type"] == "option_close"


def test_route_condition_passthrough():
    """条件函数应该直接读 state 字段。"""
    state = {"product_type": "swap"}
    assert route_product_condition(state) == "swap"
