"""Multi-instruction preparation isolates state and never repeats uncertain writes."""
import importlib.util
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest


def _instruction(raw, text, *, depends_on=None, requires_result=False):
    start = raw.index(text)
    return {"text": text, "start": start, "end": start + len(text), "evidence": text,
            "confidence": 1.0, "depends_on": depends_on or [], "requires_result": requires_result}


def _state(raw, instructions):
    return {"raw_text": raw, "sub_instructions": instructions, "message_id": 1234567890123456789,
            "conversation_id": "c", "user_id": "u", "room_id": "r", "quote_content": None,
            "conversation_orders": [], "history_messages": [], "field_records": {}}


async def test_planner_checks_original_spans_dependencies_and_coverage(monkeypatch):
    assert importlib.util.find_spec("app.graph.instructions") is not None
    from app.graph import instructions as module

    raw = "买甲；卖乙"
    plan = [_instruction(raw, "买甲"), _instruction(raw, "卖乙")]
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value=module.InstructionPlan(instructions=plan),
    )
    monkeypatch.setattr(module, "get_qwen_standard", lambda: model)
    result = await module.plan_instructions(_state(raw, []))
    assert [item["text"] for item in result["sub_instructions"]] == ["买甲", "卖乙"]
    for invalid in (
        [plan[0]], [{**plan[0], "text": "买丙"}, plan[1]],
        [{**plan[0], "depends_on": [1]}, plan[1]],
        [{**plan[0], "end": len(raw)}, plan[1]],
    ):
        with pytest.raises(ValueError):
            module.validate_instruction_plan(raw, module.InstructionPlan(instructions=invalid))


async def test_native_send_isolates_preparation_and_batches_original_message_identity(monkeypatch):
    from app.execution import operations
    from app.graph.instructions import build_instructions_graph
    from app.subgraphs.swap.backend import call_swap_backend

    calls, seen = [], []

    class Worker:
        async def ainvoke(self, state, config=None, **kwargs):
            seen.append(len(state["conversation_orders"]))
            state["conversation_orders"].append({"private": state["raw_text"]})
            update = await call_swap_backend(state, intent="place_order_request", order_list=[
                {"placeOrderWindCode": "600001.SH" if "甲" in state["raw_text"] else "600002.SH"},
            ])
            assert "api_code" not in update and "api_result" not in update
            return {**state, **update, "product_type": "swap", "intent": "place_order_request"}

    async def operate(req):
        calls.append(req.model_dump(mode="json"))
        return {"code": 0, "data": "真实批量回复：一项通过，一项业务失败"}

    monkeypatch.setattr(operations, "SwapClientHttpx", lambda: MagicMock(operate=operate))
    raw = "买甲；买乙"
    initial = _state(raw, [_instruction(raw, "买甲"), _instruction(raw, "买乙")])
    original = deepcopy(initial)
    result = await build_instructions_graph(Worker()).ainvoke(initial)
    assert initial == original and seen == [0, 0]
    assert len(calls) == 1 and len(calls[0]["orderList"]) == 2
    assert calls[0]["messageId"] == 1234567890123456789
    assert [item["status"] for item in result["instruction_results"]] == ["response_received"] * 2
    assert all(item["batch_instruction_ids"] == ["instruction-1", "instruction-2"]
               for item in result["instruction_results"])
    assert "一项业务失败" in result["reply_text"]
    close = {"product": "close", "payload": {
        "type": "close_order_request", "rawContent": "平仓", "messageContent": "平仓",
        "closeOrderReqVO": {"closeOrderList": [{"internalTradeId": "OPT-1", "qty": 10}]},
    }}
    changed = deepcopy(close)
    changed["payload"]["closeOrderReqVO"]["closeOrderList"][0]["qty"] = 20
    assert len(operations.batch_operations([
        {"instruction_id": "a", "operation": close}, {"instruction_id": "b", "operation": changed},
    ])) == 2


async def test_partial_timeout_blocks_dependents_without_repeating_write(monkeypatch):
    from app.execution import operations
    from app.graph.instructions import build_instructions_graph
    from app.subgraphs.option.backend import call_option_backend
    from app.subgraphs.swap.backend import call_swap_backend
    from app.tools.exceptions import BackendUnreachableError

    prepared, writes = [], []

    class Worker:
        async def ainvoke(self, state, config=None, **kwargs):
            prepared.append(state["raw_text"])
            if "期权" in state["raw_text"]:
                await call_option_backend(state, intent="place_order_from_quote", order_list=[{"orderId": "Q-1"}])
            else:
                await call_swap_backend(state, intent="place_order_request", order_list=[{"placeOrderWindCode": "600001.SH"}])
            return state

    async def swap(req):
        writes.append("swap")
        raise BackendUnreachableError("swap", "timeout")

    async def option(req):
        writes.append("option")
        return {"code": 0, "data": "真实期权回复"}

    monkeypatch.setattr(operations, "SwapClientHttpx", lambda: MagicMock(operate=swap))
    monkeypatch.setattr(operations, "OptionClientHttpx", lambda: MagicMock(operate=option))
    raw = "买甲；期权下单；再买乙"
    plan = [_instruction(raw, "买甲"), _instruction(raw, "期权下单"),
            _instruction(raw, "再买乙", depends_on=[0])]
    result = await build_instructions_graph(Worker()).ainvoke(_state(raw, plan))
    assert sorted(writes) == ["option", "swap"] and "再买乙" not in prepared
    assert [item["status"] for item in result["instruction_results"]] == ["uncertain", "response_received", "blocked"]


async def test_dependent_distinct_operations_wait_dedup_window_and_keep_same_identity(monkeypatch):
    from app.execution import operations
    from app.graph.instructions import build_instructions_graph
    from app.subgraphs.swap.backend import call_swap_backend

    clock, waits, sent = [100.0], [], []

    async def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    class Worker:
        async def ainvoke(self, state, config=None, **kwargs):
            await call_swap_backend(state, intent="place_order_request", order_list=[
                {"placeOrderWindCode": "600001.SH"},
            ])
            return state

    async def operate(req):
        sent.append((clock[0], req.message_id))
        return {"code": 0, "data": "真实回复"}

    monkeypatch.setattr(operations, "SwapClientHttpx", lambda: MagicMock(operate=operate))
    raw = "买甲；再买甲"
    plan = [_instruction(raw, "买甲"), _instruction(raw, "再买甲", depends_on=[0])]
    await build_instructions_graph(Worker(), clock=lambda: clock[0], sleep=sleep).ainvoke(_state(raw, plan))
    assert waits == [10.0]
    assert sent == [(100.0, 1234567890123456789), (110.0, 1234567890123456789)]


async def test_dependent_confirmation_never_synthesizes_quote(monkeypatch):
    from app.execution import operations
    from app.graph.instructions import build_instructions_graph
    from app.subgraphs.swap.backend import call_swap_backend
    from app.subgraphs.swap.confirm import swap_confirm

    writes = []

    class Worker:
        async def ainvoke(self, state, config=None, **kwargs):
            if "确认" in state["raw_text"]:
                assert state.get("quote_content") is None
                return {**state, **await swap_confirm({**state, "intent": "confirm_order"})}
            await call_swap_backend(state, intent="place_order_request", order_list=[{"placeOrderWindCode": "600001.SH"}])
            return state

    async def operate(req):
        writes.append(req)
        return {"code": 0, "data": {"orderId": "H-20260918-1234567890"}}

    monkeypatch.setattr(operations, "SwapClientHttpx", lambda: MagicMock(operate=operate))
    raw = "买甲；确认下单"
    plan = [_instruction(raw, "买甲"), _instruction(raw, "确认下单", depends_on=[0], requires_result=True)]
    result = await build_instructions_graph(Worker()).ainvoke(_state(raw, plan))
    assert len(writes) == 1
    assert result["instruction_results"][1]["status"] == "needs_input"
    assert "引用" in result["reply_text"]


async def test_actual_text_receipt_binds_only_its_unique_order_to_dependent_query(monkeypatch):
    from app.execution import operations
    from app.graph.instructions import build_instructions_graph
    from app.subgraphs.swap.backend import call_swap_backend

    writes = []

    class Worker:
        async def ainvoke(self, state, config=None, **kwargs):
            query = "查" in state["raw_text"]
            await call_swap_backend(
                state, intent="query_order_status" if query else "place_order_request",
                order_list=[{"orderId": None}] if query else [{"placeOrderWindCode": "600001.SH"}],
            )
            return state

    async def operate(req):
        writes.append(req.model_dump(mode="json"))
        return {"code": 0, "data": "-----场外收益互换申请-----\n单号：H-20260918-1234567890\n状态：待确认"}

    monkeypatch.setattr(operations, "SwapClientHttpx", lambda: MagicMock(operate=operate))
    raw = "买甲；查刚才那笔"
    plan = [_instruction(raw, "买甲"), _instruction(raw, "查刚才那笔", depends_on=[0], requires_result=True)]
    result = await build_instructions_graph(Worker()).ainvoke(_state(raw, plan))
    assert len(writes) == 2
    assert writes[1]["orderList"][0]["orderId"] == "H-20260918-1234567890"
    assert writes[1]["quoteContent"] is None
    assert result["instruction_results"][1]["status"] == "response_received"
