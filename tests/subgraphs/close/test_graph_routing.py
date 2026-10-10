"""产品子图按联合结果执行一个动作，保留当前 Java wire 与未知兜底。"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.clients import _ChatLLM
from app.subgraphs.close.graph import build_close_graph
from tests.joint_support import instruction_data


@pytest.mark.parametrize("intent,raw,node,quote", [('close_order_query', '查可平持仓', 'close_holding_query', ''), ('close_order_request', 'CO-20260922-ABCDEF12 平100万市价', 'close_place_close', ''), ('close_order_confirm', '确认平仓', 'close_confirm_close', 'CO-20260922-ABCDEF12'), ('close_order_cancel_request', '撤单', 'close_cancel_close', 'CO-20260922-ABCDEF12'), ('close_order_cancel_confirm', '确认撤单', 'close_confirm_cancel', 'CO-20260922-ABCDEF12'), ('close_order_order_query', '查询 CO-20260922-ABCDEF12', 'close_query_status', '')])
async def test_each_action_reaches_one_java_call_without_model(monkeypatch, intent, raw, node, quote):
    """只替换外部边界，路由、来源检查和 DTO 均走真实实现。"""
    no_model = MagicMock(side_effect=AssertionError("产品子图不允许模型请求"))
    monkeypatch.setattr(_ChatLLM, "with_structured_output", no_model)
    backend = AsyncMock(return_value={"code": 0, "data": "Java receipt"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    orders = []
    if intent == "new_inquiry":
        orders = [{"stockCode": "茅台"}]
    elif intent in {"place_order_from_quote", "confirm_order"}:
        orders = [{"orderId": quote}]
    elif intent == "close_order_request":
        orders = [{"orderId": "CO-20260922-ABCDEF12", "closeOrderNotionalDelta": "1000000", "closeOrderType": "市价单"}]
    parsed = instruction_data("option_close", intent, raw, orders=orders, quote=quote)
    result = await build_close_graph().ainvoke({"raw_text": raw, "quote_content": quote,
        "conversation_id": "c", "message_id": 1, "user_id": "u", "room_id": "r", "parsed_instruction": parsed})
    assert not result.get("error"), result
    assert result["api_result"] == "Java receipt"
    assert backend.await_count == 1
    assert backend.await_args.args[0].type == intent
    no_model.assert_not_called()


async def test_unknown_intent_never_calls_backend(monkeypatch):
    """结构有效的未知意图也只进入兜底，不用空参数尝试交易。"""
    backend = AsyncMock()
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    result = await build_close_graph().ainvoke({"raw_text": "你好", "parsed_instruction":
        instruction_data("option_close", "unknown_intent", "你好")})
    assert not result.get("error")
    backend.assert_not_called()
