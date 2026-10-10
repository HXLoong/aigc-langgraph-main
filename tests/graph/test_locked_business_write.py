"""A locked ledger must also protect actual business payloads."""
import importlib
from unittest.mock import AsyncMock, MagicMock

from langgraph.graph import END, START, StateGraph

from app.extraction.fields import FieldRecord
from app.graph.safe_node import safe_node
from app.graph.state import AgentState


async def test_locked_value_cannot_be_changed_by_a_downstream_node():
    @safe_node
    async def overwrite(state):
        return {"place_params": {"orderList": [{"placeOrderQuantity": 500}]}}

    graph = StateGraph(AgentState)
    graph.add_node("overwrite", overwrite)
    graph.add_edge(START, "overwrite")
    graph.add_edge("overwrite", END)
    path = "swap/place_order.orderList.0.placeOrderQuantity"
    result = await graph.compile().ainvoke({"field_records": {
        path: FieldRecord(value=100, source="user", evidence="100股", locked=True),
    }})
    assert result["place_params"]["orderList"][0]["placeOrderQuantity"] == 100
    assert result["field_records"][path].value == 100
    assert result["field_records"][path].rejected_updates == 1


async def test_locked_value_is_checked_before_backend_side_effect(monkeypatch):
    module = importlib.import_module("app.subgraphs.swap.backend")
    client = MagicMock()
    client.operate = AsyncMock(return_value={"code": 0, "data": "真实回复"})
    monkeypatch.setattr(module, "SwapClientHttpx", lambda: client)
    await module.call_swap_backend({
        "user_id": "u", "room_id": "r", "message_id": 1, "conversation_id": "c",
        "raw_text": "买入100股", "message_content": "买入100股",
        "field_records": {"swap/place_order.orderList.0.placeOrderQuantity":
            FieldRecord(value=100, source="user", locked=True)},
    }, intent="place_order_request", order_list=[{"placeOrderQuantity": 500}])
    assert client.operate.await_args.args[0].order_list[0].place_order_quantity == 100


async def test_close_params_state_is_protected_as_well_as_backend_payload():
    @safe_node
    async def overwrite(state):
        return {"close_params": {"closeOrderList": [{"closeOrderNotionalDelta": "5000000"}]}}

    path = "close/place_close.orderList.0.closeOrderNotionalDelta"
    graph = StateGraph(AgentState)
    graph.add_node("overwrite", overwrite)
    graph.add_edge(START, "overwrite")
    graph.add_edge("overwrite", END)
    result = await graph.compile().ainvoke({"field_records": {
        path: FieldRecord(value="1000000", source="user", evidence="100万", locked=True),
    }})
    assert result["close_params"]["closeOrderList"][0]["closeOrderNotionalDelta"] == "1000000"
    assert result["field_records"][path].rejected_updates == 1
