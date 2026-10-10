"""确认只提交当前明确身份和增量，旧卡片及历史不作为完整订单。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from tests.joint_support import instruction_data

ORDER = "Q-20260922-0000000001"
QUOTE = f"单号：{ORDER}\n标的：茅台\n期限：1M\n名义本金：200万"


@pytest.mark.parametrize("raw,extra", [("确认下单", {}), ("确认下单 限价12", {"limitPrice": 12}), ("2M 确认下单", {"tenor": "2M"})])
async def test_confirmation_submits_current_increment(monkeypatch, raw, extra):
    """历史记忆中其它订单不会替换当前引用。"""
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "Java receipt"})
    monkeypatch.setattr("app.subgraphs.option.extract_confirm_place.prepare_option_request", backend)
    orders = [{"orderId": ORDER, **extra}]
    result = await option_extract_confirm_place({"raw_text": raw, "quote_content": QUOTE,
        "last_confirmed_params": {"order_ids": ["Q-20260922-9999999999"]},
        "parsed_instruction": instruction_data("option", "confirm_order", raw, orders=orders, quote=QUOTE)})
    assert not result.get("error"), result
    assert backend.await_args.kwargs["order_list"] == orders
    assert result["confirm"] == {"action": "place", "orderList": orders}


async def test_history_cannot_authorize_bare_confirmation(monkeypatch):
    """本轮没有订单身份时不能从记忆补齐并交易。"""
    backend = AsyncMock()
    monkeypatch.setattr("app.subgraphs.option.extract_confirm_place.prepare_option_request", backend)
    result = await option_extract_confirm_place({"raw_text": "确认下单", "last_confirmed_params": {"order_ids": [ORDER]}})
    assert result.get("reply_text")
    backend.assert_not_called()
