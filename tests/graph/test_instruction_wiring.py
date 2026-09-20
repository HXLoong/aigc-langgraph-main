"""真实主图接多指令准备/提交；隔离后的子图不能再次持久化或递归规划。"""
from unittest.mock import AsyncMock, MagicMock

from app.api.routes import _state_to_outputs
from app.graph import main
from app.graph.retry import io_node


async def test_main_graph_batches_multi_instructions_and_exposes_original_receipt(monkeypatch):
    from app.execution import operations
    from app.graph.instructions import InstructionPlan, validate_instruction_plan
    from app.subgraphs.swap import backend
    from app.subgraphs.swap.backend import call_swap_backend

    raw = "买甲；买乙"
    plan = validate_instruction_plan(raw, InstructionPlan(instructions=[
        {"text": text, "evidence": text, "start": start, "end": start + 2, "confidence": 1}
        for text, start in (("买甲", 0), ("买乙", 3))
    ]))
    async def prepare(state):
        assert state.get("place_params") is None
        response = await call_swap_backend(state, intent="place_order_request", order_list=[{
            "placeOrderWindCode": "600001.SH" if "甲" in state["raw_text"] else "600002.SH",
        }])
        assert "api_code" not in response
        return {**response, "intent": "place_order_request"}

    @io_node
    async def plan_node(state):
        return {"sub_instructions": plan}

    @io_node
    async def intent_node(state):
        return {"product_type": "swap"}

    monkeypatch.setattr(main, "plan_instructions", plan_node, raising=False)
    monkeypatch.setattr(main, "pre_route", AsyncMock(return_value={}))
    monkeypatch.setattr(main, "intent_route", intent_node)
    monkeypatch.setattr(main, "build_swap_graph", lambda: prepare)
    audit = AsyncMock(return_value={})
    monkeypatch.setattr(main, "persist", audit)
    client = MagicMock(operate=AsyncMock(return_value={"code": 0, "data": "原始批量后端回执"}))
    monkeypatch.setattr(operations, "SwapClientHttpx", lambda: client)
    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: MagicMock(
        operate=AsyncMock(side_effect=AssertionError("preparation must not call a live backend")),
    ))
    message_factory = MagicMock()
    output = await main.build_main_graph(message_client_factory=message_factory).ainvoke({
        "raw_text": raw, "message_id": "1234567890123456789", "conversation_id": "conversation",
        "user_id": "user", "room_id": "room",
    })
    assert client.operate.await_count == 1
    request = client.operate.await_args.args[0]
    assert request.message_id == 1234567890123456789 and len(request.order_list) == 2
    assert output["reply_text"].count("原始批量后端回执") == 1
    assert len(_state_to_outputs(output)["instruction_results"]) == 2
    message_factory.assert_not_called()
    audit.assert_awaited_once()


async def test_instruction_worker_stops_before_plan_history_and_audit(monkeypatch):
    plan = AsyncMock(side_effect=AssertionError("nested planning"))
    audit = AsyncMock(side_effect=AssertionError("nested audit"))
    @io_node
    async def plan_node(state):
        return await plan(state)

    @io_node
    async def intent_node(state):
        return {"product_type": "unknown"}

    monkeypatch.setattr(main, "plan_instructions", plan_node, raising=False)
    monkeypatch.setattr(main, "persist", audit)
    monkeypatch.setattr(main, "pre_route", AsyncMock(return_value={}))
    monkeypatch.setattr(main, "intent_route", intent_node)
    result = await main.build_main_graph(_instruction_worker=True).ainvoke({"raw_text": "独立输入"})
    assert not result.get("history_messages")
    plan.assert_not_awaited()
    audit.assert_not_awaited()
