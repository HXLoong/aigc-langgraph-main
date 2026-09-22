"""一条消息只走一个业务分支；同一动作仍可携带多笔订单。"""
from __future__ import annotations

from typing import Any, TypedDict
from unittest.mock import AsyncMock, Mock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.api.routes import _state_to_outputs
from app.graph import main
from app.graph.state import AgentState, Message
from app.llm.clients import _ChatLLM
from app.subgraphs.swap.backend import call_swap_backend


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch) -> Mock:
    model = Mock(side_effect=AssertionError("ordinary routing must not invoke a planner"))
    monkeypatch.setattr(_ChatLLM, "with_structured_output", model)
    return model


def test_ordinary_entry_goes_directly_to_product_routing() -> None:
    graph = main.build_main_graph().get_graph()
    assert {edge.target for edge in graph.edges if edge.source == "entry_route"} == {
        "quick_inquiry", "existing_command_query", "pre_route",
    }
    assert "plan_instructions" not in graph.nodes
    assert "instructions" not in graph.nodes


@pytest.mark.parametrize("raw", [
    "互换买入600519 100股",
    "互换买入600519\n100股",
    "互换买入600519 100股；限价1500",
    "互换买入600519 100股，不要卖出",
    "撤单 H-20260922-0000000001，然后期权询价600519 1M",
])
async def test_original_message_enters_one_business_branch(
    monkeypatch: pytest.MonkeyPatch, no_model: Mock, raw: str,
) -> None:
    business = AsyncMock(return_value={"intent": "place_order_request", "api_code": 0,
                                       "api_result": "Java 原始回执"})
    option = AsyncMock(return_value={})
    close = AsyncMock(return_value={})
    monkeypatch.setattr(main, "build_swap_graph", lambda: business)
    monkeypatch.setattr(main, "build_option_graph", lambda: option)
    monkeypatch.setattr(main, "build_close_graph", lambda: close)
    audit = AsyncMock(return_value={})
    monkeypatch.setattr(main, "persist", audit)
    message_client = Mock(set_intent=AsyncMock())
    graph = main.build_main_graph(message_client_factory=lambda: message_client)
    result = await graph.ainvoke({
        "raw_text": raw, "message_content": raw, "message_id": 1234567890123456789,
        "conversation_id": "single-action", "room_id": "room", "user_id": "user",
    })

    assert result.get("error") is None
    assert result["reply_text"] == "Java 原始回执"
    business.assert_awaited_once()
    assert business.await_args.args[0]["raw_text"] == raw
    option.assert_not_awaited()
    close.assert_not_awaited()
    no_model.assert_not_called()
    message_client.set_intent.assert_awaited_once()
    request = message_client.set_intent.await_args.args[0]
    assert request.intent == "place_order_request" and request.product_type == 1
    audit.assert_awaited_once()
    assert [(message.role, message.content) for message in result["history_messages"]] == [
        ("user", raw), ("assistant", "Java 原始回执"),
    ]
    assert "instruction_results" not in _state_to_outputs(result)


async def test_single_action_submits_both_orders_and_keeps_original_receipt(
    monkeypatch: pytest.MonkeyPatch, no_model: Mock,
) -> None:
    orders = [
        {"placeOrderWindCode": "600519", "placeOrderQuantity": 100,
         "placeOrderOrderDirection": "BUY"},
        {"placeOrderWindCode": "000001", "placeOrderQuantity": 200,
         "placeOrderOrderDirection": "SELL"},
    ]

    async def submit(state: AgentState) -> dict[str, Any]:
        result = await call_swap_backend(state, intent="place_order_request", order_list=orders)
        return {**result, "intent": "place_order_request", "expected_action": "place"}

    receipt = "单号：H-20260922-0000000001\n单号：H-20260922-0000000002"
    client = Mock(operate=AsyncMock(return_value={"code": 0, "data": receipt}))
    monkeypatch.setattr("app.subgraphs.swap.backend.SwapClientHttpx", lambda: client)
    monkeypatch.setattr(main, "build_swap_graph", lambda: submit)
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    raw = "互换买入600519 100股；卖出000001 200股"
    result = await main.build_main_graph().ainvoke({
        "raw_text": raw, "message_content": raw, "message_id": 1234567890123456789,
        "conversation_id": "batch-order", "room_id": "room", "user_id": "user",
    })

    assert result.get("error") is None
    client.operate.assert_awaited_once()
    request = client.operate.await_args.args[0].model_dump(mode="json", by_alias=True)
    assert request["type"] == "place_order_request"
    assert request["rawContent"] == raw and request["messageId"] == 1234567890123456789
    assert [order["placeOrderOrderDirection"] for order in request["orderList"]] == ["BUY", "SELL"]
    assert [order["placeOrderQuantity"] for order in request["orderList"]] == [100, 200]
    assert result["reply_text"] == receipt and result["api_result"] == receipt
    assert result["last_confirmed_params"]["order_ids"] == [
        "H-20260922-0000000001", "H-20260922-0000000002",
    ]
    no_model.assert_not_called()


class _LegacyState(TypedDict):
    history_messages: list[Message]
    product_type: str
    intent: str
    sub_instructions: list[dict[str, Any]]
    instruction_results: list[dict[str, Any]]


@pytest.mark.parametrize("unsupported_file", [False, True])
async def test_completed_legacy_checkpoint_preserves_history_without_execution_state(
    monkeypatch: pytest.MonkeyPatch, no_model: Mock, unsupported_file: bool,
) -> None:
    saver = InMemorySaver()
    config = {"configurable": {"thread_id": "legacy-single-action"}}
    legacy = StateGraph(_LegacyState)
    legacy.add_node("ingest", lambda state: state)
    legacy.add_edge(START, "ingest")
    legacy.add_edge("ingest", END)
    await legacy.compile(checkpointer=saver).ainvoke({
        "history_messages": [Message(role="assistant", content="历史回执")],
        "product_type": "unknown", "intent": "multi_instruction",
        "sub_instructions": [{"text": "旧计划不得再次提交"}],
        "instruction_results": [{"status": "response_received", "api_result": "旧结果"}],
    }, config=config)
    business = AsyncMock(return_value={"intent": "place_order_request", "api_code": 0,
                                       "api_result": "本轮回执"})
    monkeypatch.setattr(main, "build_swap_graph", lambda: business)
    monkeypatch.setattr(main, "persist", AsyncMock(return_value={}))
    message_client = Mock(set_intent=AsyncMock())
    result = await main.build_main_graph(saver, lambda: message_client).ainvoke({
        "raw_text": "互换买入600519 100股", "message_id": 2, "conversation_id": "legacy-single-action",
        "input_files": [{"type": "document", "extension": ".pdf"}] if unsupported_file else [],
    }, config=config)

    assert result.get("error") is None
    assert result["history_messages"][0].content == "历史回执"
    assert result["history_messages"][-1].content == result["reply_text"]
    assert result["intent"] != "multi_instruction"
    assert "sub_instructions" not in result
    assert "instruction_results" not in result
    assert "instruction_results" not in _state_to_outputs(result)
    message_client.set_intent.assert_awaited_once()
    if unsupported_file:
        business.assert_not_awaited()
        assert message_client.set_intent.await_args.args[0].intent == "unknown_intent"
    else:
        business.assert_awaited_once()
        assert result["reply_text"] == "本轮回执"
    no_model.assert_not_called()


def test_new_response_does_not_project_legacy_instruction_results() -> None:
    assert "instruction_results" not in _state_to_outputs({
        "instruction_results": [{"status": "response_received"}],
    })
