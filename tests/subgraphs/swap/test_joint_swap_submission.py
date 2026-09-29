"""互换子图共享主图解析结果，候选处理和提交不再消耗模型额度。"""
from __future__ import annotations

from app.llm.clients import _ChatLLM
from app.parsing.models import SwapInstruction
from app.subgraphs.swap.graph import build_swap_graph


async def test_swap_subgraph_uses_joint_result_without_second_model(monkeypatch) -> None:
    """Java 接收一次解析的参数，接口装配不重算数值或补默认值。"""
    raw = "茅台买入1.5万股限价2"
    parsed = SwapInstruction.model_validate({
        "product_type": "swap", "intent": "place_order_request", "confidence": 0.9,
        "evidence": [{"origin": "raw", "text": raw}],
        "orders": [{"placeOrderWindCode": "茅台", "placeOrderQuantity": 15000,
                    "placeOrderOrderDirection": "BUY", "placeOrderPrice": 2}],
        "fields": [{"path": f"orders.0.{key}", "origin": "raw", "text": text}
                   for key, text in (("placeOrderWindCode", "茅台"), ("placeOrderQuantity", "1.5万股"),
                                     ("placeOrderOrderDirection", "买入"), ("placeOrderPrice", "限价2"))],
    })
    requests = []

    def no_model(self, *args, **kwargs):
        """覆盖所有模型工厂的真实边界，旧节点调用也会被检测。"""
        raise AssertionError("互换子图不能再调用模型")

    async def operate(self, request):
        """记录真实 DTO 参数，不替换图内处理。"""
        requests.append(request.model_dump(mode="json", exclude_none=True))
        return {"code": 0, "data": "Java swap card", "msg": ""}

    monkeypatch.setattr(_ChatLLM, "with_structured_output", no_model)
    monkeypatch.setattr("app.tools.swap_client.SwapClientHttpx.operate", operate)
    update = await build_swap_graph().ainvoke({"raw_text": raw, "conversation_id": "swap-test",
        "room_id": "room", "user_id": "user", "message_id": 3,
        "parsed_instruction": parsed.model_dump(exclude_none=True, exclude_unset=True)})
    assert update.get("error") is None
    assert len(requests) == 1
    assert requests[0]["orderList"] == [{"placeOrderWindCode": "茅台", "placeOrderQuantity": 15000,
                                        "placeOrderOrderDirection": "BUY", "placeOrderPrice": "2"}]
    assert update["api_result"] == "Java swap card"


async def test_joint_picks_survive_internal_graph_and_reach_java(monkeypatch):
    """准备图必须把选择指针交给父图，最终只提交所选候选。"""
    from unittest.mock import AsyncMock

    from tests.joint_support import instruction_data

    oid = "H-20260922-0000000001"
    raw = "标的1，对手A"
    quote = f"订单{oid}（序号1）\n1.600519.SH 茅台\nA.甲账户"
    parsed = instruction_data("swap", "place_order_request", raw, quote=quote, orders=[{"orderId": oid}],
        ticker_picks=[{"idx": 0, "seq": 1, "evidence": "标的1", "confidence": .9}],
        counterparty_picks=[{"idx": 0, "letter": "A", "evidence": "对手A", "confidence": .9}])
    backend = AsyncMock(return_value={"code": 0, "data": "Java selected receipt"})
    monkeypatch.setattr("app.tools.swap_client.SwapClientHttpx.operate", backend)
    result = await build_swap_graph().ainvoke({"raw_text": raw, "quote_content": quote,
        "conversation_id": "c", "message_id": 1, "room_id": "r", "user_id": "u", "parsed_instruction": parsed,
        "swap_counterparties": [{"sort": "A", "shortName": "甲账户"}],
        "quote_ticker_candidates": [{"orderId": oid, "candidates": [{"seq": 1, "code": "600519.SH", "name": "茅台"}]}]})
    assert not result.get("error"), result
    order = backend.await_args.args[0].model_dump(exclude_none=True)["orderList"][0]
    assert order == {"orderId": oid, "placeOrderWindCode": "600519.SH", "placeOrderShortname": "甲账户"}
    assert "swap_ticker_picks" not in result and "swap_counterparty_picks" not in result
