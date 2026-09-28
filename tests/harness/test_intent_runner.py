"""冻结意图只执行服务端联合解析，某轮失败不污染后续轮输入。"""
from __future__ import annotations

import json

import httpx

from harness.golden import GoldenCase, TurnSpec
from harness.intent_runner import requires_replay, run_frozen_case, turn_state


def test_turn_state_uses_frozen_context_and_authorized_fixture():
    """输入投影只带原文、引用和冻结历史，不含 expected。"""
    from mock_api.backend.fixtures import COUNTERPARTIES

    turn = TurnSpec(send_text="确认平仓", quote_content="CO-20260923-12345678",
        history=[{"role": "user", "content": "我想平仓"}], prev_product_type="option_close",
        expected={"intent": "close_order_confirm"})
    state = turn_state(turn, conversation_id="c")
    assert state["product_type"] == "option_close" and state["quote_content"] == turn.quote_content
    assert state["history_messages"] == turn.history
    assert state["option_counterparties"] == state["swap_counterparties"] == COUNTERPARTIES
    assert "expected" not in state


def test_reference_dependencies_choose_main_graph_replay():
    """只有需要前轮真实输出时才走全链路回放。"""
    assert not requires_replay([{"send_text": "查持仓", "quote_previous": False}])
    assert requires_replay([{"send_text": "查持仓"}, {"send_text": "确认", "quote_previous": True}])
    assert requires_replay([{"send_text": "查询 {{previous_order_id}}"}])


async def test_every_frozen_turn_is_attempted_after_node_failure():
    """冻结第二轮不依赖第一轮正确性，执行结果仍记录第一轮失败。"""
    requests = []

    def response(request):
        """只允许请求节点 API，不能在评测进程内跑交易图。"""
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/nodes/run" and body["node"] == "parse_instruction"
        output = {"error": {"type": "ValueError", "message": "first"}} if len(requests) == 1 else {"intent": "close_order_confirm", "product_type": "option_close"}
        return httpx.Response(200, json={"output": output})

    case = GoldenCase(id="frozen", category="intent/option_close", turns=[
        {"send_text": "查持仓", "quote_previous": False},
        {"send_text": "确认平仓", "quote_previous": False, "quote_content": "FROZEN_QUOTE"},
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await run_frozen_case(case, base_url="http://test", user_id="u", client=client)
    assert len(result.turns) == len(requests) == 2
    assert result.failure and result.failure["turn"] == 1
    assert requests[1]["state"]["quote_content"] == "FROZEN_QUOTE"
    assert requests[1]["state"]["history_messages"] == []
