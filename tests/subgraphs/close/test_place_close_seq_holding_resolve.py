"""平仓身份与引用选择范围检查，不计算持仓或补历史参数。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.close.place_close import close_place_close
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes

FIRST, SECOND = "CO-20260922-AAAA0001", "CO-20260922-BBBB0002"
QUOTE = f"序号：2\n单号：{FIRST}\n合约编号：OPT-AAAA1\n序号：4\n单号：{SECOND}\n合约编号：OPT-BBBB2"


@pytest.mark.parametrize("raw,order,valid", [
    ("第一笔全平", {"orderId": FIRST, "internalTradeId": "OPT-AAAA1", "confirmFullClose": True}, True),
    ("序号4全平", {"orderId": SECOND, "internalTradeId": "OPT-BBBB2", "confirmFullClose": True}, True),
    ("第二笔全平", {"internalTradeId": "OPT-BBBB2", "confirmFullClose": True}, True),
    ("第一笔全平", {"orderId": SECOND}, False),
    ("序号3全平", {"orderId": FIRST}, False),
    ("第一笔全平", {"orderId": FIRST, "internalTradeId": "OPT-BBBB2"}, False),
    (f"{FIRST}、{SECOND}全平", {"orderId": FIRST}, False),
])
async def test_reference_selection_is_unique_complete_and_consistent(monkeypatch, raw, order, valid):
    """用户选择不得串单、扩单或漏单，错误时不调用后端。"""
    backend = AsyncMock(return_value={"code": 0, "data": "Java receipt"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    parsed = instruction_data("option_close", "close_order_request", raw, orders=[order], quote=QUOTE)
    result = await run_request_nodes(close_place_close, {"raw_text": raw, "quote_content": QUOTE, "conversation_id": "c",
        "room_id": "r", "user_id": "u", "message_id": 1, "parsed_instruction": parsed}, "close")
    if valid:
        assert not result.get("error"), result
        assert backend.await_count == 1
    else:
        assert result.get("error"), result
        backend.assert_not_called()


async def test_raw_contract_cannot_mask_another_quoted_order_id(monkeypatch):
    """输入按合约选中第一笔时，模型不能混入第二笔单号。"""
    backend = AsyncMock(return_value={"code": 0, "data": "unexpected"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    raw = "OPT-AAAA1 全平"
    parsed = instruction_data("option_close", "close_order_request", raw,
        orders=[{"orderId": SECOND, "internalTradeId": "OPT-AAAA1", "confirmFullClose": True}], quote=QUOTE)
    result = await run_request_nodes(close_place_close, {"raw_text": raw, "quote_content": QUOTE, "conversation_id": "c",
        "message_id": 1, "room_id": "r", "user_id": "u", "parsed_instruction": parsed}, "close")
    assert result.get("error")
    backend.assert_not_called()
