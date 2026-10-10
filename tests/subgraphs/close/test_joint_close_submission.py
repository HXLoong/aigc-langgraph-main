"""平仓子图只读取联合参数，金额校验与旧订单合并由 Java 完成。"""
from __future__ import annotations

from unittest.mock import AsyncMock

from app.llm.clients import _ChatLLM
from app.parsing.models import CloseInstruction
from app.subgraphs.close.holding_query import close_holding_query
from app.subgraphs.close.place_close import close_place_close
from tests.request_support import run_request_nodes


def _no_second_model(self, *args, **kwargs):
    """任何子图模型请求都违反本次调用的一次解析边界。"""
    raise AssertionError("产品子图不再调用模型")


async def test_close_passes_extracted_amount_to_java_without_local_range_check(monkeypatch) -> None:
    """负值仍按用户提取值提交，由 Java 返回权威业务拒绝。"""
    raw, contract = "第一笔，平仓-1元", "OPT-TEST20260001"
    quote = f"序号：1\n合约编号：{contract}"
    parsed = CloseInstruction.model_validate({
        "product_type": "option_close", "intent": "close_order_request", "confidence": 0.9,
        "evidence": [{"origin": "raw", "text": "平仓-1元"}],
        "orders": [{"internalTradeId": contract, "closeOrderNotionalDelta": "-1"}],
        "fields": [{"path": "orders.0.internalTradeId", "origin": "quote", "text": contract},
                   {"path": "orders.0.closeOrderNotionalDelta", "origin": "raw", "text": "-1元"}],
    })
    requests = []

    async def operate(self, request):
        """观察真实序列化后的业务参数和拒绝回执。"""
        requests.append(request.model_dump(exclude_none=True))
        return {"code": 501, "data": None, "msg": "Java: 金额无效"}

    monkeypatch.setattr(_ChatLLM, "with_structured_output", _no_second_model)
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", operate)
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.query_close_orders", AsyncMock(return_value={"code": 0, "data": []}))
    update = await run_request_nodes(close_place_close, {"raw_text": raw, "quote_content": quote,
        "conversation_id": "close-test", "message_id": 1, "room_id": "room", "user_id": "user",
        "parsed_instruction": parsed.model_dump(exclude_none=True, exclude_unset=True)}, "close")
    assert update.get("error") is None
    assert requests[0]["closeOrderReqVO"]["closeOrderList"] == [{"internalTradeId": contract, "closeOrderNotionalDelta": "-1"}]
    assert update["api_code"] == 501 and update["api_result"] == "Java: 金额无效"


async def test_holding_query_uses_parsed_filters_without_model_or_defaults(monkeypatch) -> None:
    """查询只发送明确过滤条件，不追加模型请求或未提供的业务默认值。"""
    parsed = CloseInstruction.model_validate({
        "product_type": "option_close", "intent": "close_order_query", "confidence": 0.9,
        "evidence": [{"origin": "raw", "text": "查持仓"}],
    })
    requests = []

    async def operate(self, request):
        """记录查询 wire，不模拟业务组装。"""
        requests.append(request.model_dump(exclude_none=True))
        return {"code": 0, "data": "Java holdings", "msg": ""}

    monkeypatch.setattr(_ChatLLM, "with_structured_output", _no_second_model)
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", operate)
    update = await run_request_nodes(close_holding_query, {"raw_text": "查持仓", "conversation_id": "close-test",
        "message_id": 2, "room_id": "room", "user_id": "user",
        "parsed_instruction": parsed.model_dump(exclude_none=True, exclude_unset=True)}, "close")
    assert update.get("error") is None
    assert requests[0]["closeOrderReqVO"]["contractQuery"] == {}


def test_order_and_contract_must_identify_the_same_selected_holding() -> None:
    """不能用正确订单号掩盖同条目中的错误合约编号。"""
    import pytest

    from app.subgraphs.close.selection import validate_close_selection

    state = {"raw_text": "第一笔，全平", "quote_content":
             "序号：1\n合约编号：OPT-ONE\n单号：CO-20260928-AABBCCDD"}
    with pytest.raises(ValueError, match="范围"):
        validate_close_selection(state, [{"orderId": "CO-20260928-AABBCCDD", "internalTradeId": "OPT-TWO"}])


async def test_holding_query_without_filter_does_not_invent_closeable_default(monkeypatch):
    """只查询持仓时可以不带过滤条件，默认范围由 Java 决定。"""
    from unittest.mock import AsyncMock

    from app.subgraphs.close import holding_query
    from tests.joint_support import instruction_data

    backend = AsyncMock(return_value={"api_code": 0, "api_result": "Java holdings"})
    monkeypatch.setattr(holding_query, "prepare_close_request", backend)
    result = await holding_query.close_holding_query({"raw_text": "查持仓",
        "parsed_instruction": instruction_data("option_close", "close_order_query", "查持仓", query={})})
    assert not result.get("error"), result
    assert backend.await_args.kwargs["close_order_req_vo"] == {"contractQuery": {}}
