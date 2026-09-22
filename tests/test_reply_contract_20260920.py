from unittest.mock import AsyncMock

import pytest

from app.api.idempotency import response_is_uncertain
from app.nodes.render import _render_branch
from app.subgraphs.close.backend import call_close_backend
from app.tools.exceptions import EmptyBackendResultError, MissingBackendContextError


@pytest.mark.asyncio
async def test_close_requires_message_id_before_dispatch(monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr("app.subgraphs.close.backend.OptionClientHttpx.operate", call)
    with pytest.raises(MissingBackendContextError):
        await call_close_backend(
            {"conversation_id": "c", "room_id": "r", "user_id": "u"},
            intent="close_order_confirm",
            close_order_req_vo={},
        )
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_close_receipt_is_uncertain(monkeypatch):
    call = AsyncMock(return_value={"code": 0, "data": None})
    monkeypatch.setattr("app.subgraphs.close.backend.OptionClientHttpx.operate", call)
    with pytest.raises(EmptyBackendResultError):
        await call_close_backend(
            {"conversation_id": "c", "room_id": "r", "user_id": "u", "message_id": 123},
            intent="close_order_confirm",
            close_order_req_vo={},
        )
    assert call.await_count == 1


def test_empty_receipt_keeps_idempotency_claim():
    assert response_is_uncertain(
        {
            "data": {
                "outputs": {
                    "error": {"type": "EmptyBackendResultError"},
                }
            }
        }
    )


@pytest.mark.parametrize(
    "state",
    [
        {"confirm": {"action": "close", "confirmOrderNoList": ["CO-123"]}},
        {"confirm": {"orderList": [{"orderId": "Q-123"}]}},
        {"close_params": {"closeOrderList": [{"orderId": "CO-123"}]}},
        {"cancel_params": {"cancelOrderNoList": ["CO-123"]}},
    ],
)
def test_no_local_business_receipt_without_java(state):
    update, _ = _render_branch(
        {"product_type": "option_close", "intent": "close_order_confirm", **state}
    )
    reply = update.get("reply_text", "")
    assert reply and all(text not in reply for text in ("已提交", "已确认", "已收到", "申请时间"))


def test_java_500_reply_policy_retains_original_result():
    state = {"product_type": "option", "api_code": 500, "api_result": "内部业务异常详情"}
    update, _ = _render_branch(state)
    assert update["reply_text"] == "交易指令服务暂不可用"
    assert state["api_result"] == "内部业务异常详情"


def test_default_reply_matches_business_guidance():
    from app.config import Settings

    reply = Settings.model_fields["default_reply"].default
    assert reply.startswith("抱歉，我们目前无法识别您的意图。")
    assert "1.期权询价" in reply and "4.互换下单" in reply


@pytest.mark.parametrize("target", ["option", "swap", "close"])
async def test_invalid_json_after_dispatch_stays_uncertain(monkeypatch, target):
    import importlib

    from app.tools.exceptions import BackendUnreachableError

    module = importlib.import_module(f"app.subgraphs.{target}.backend")
    cls = "SwapClientHttpx" if target == "swap" else "OptionClientHttpx"
    monkeypatch.setattr(
        getattr(module, cls), "operate", AsyncMock(side_effect=ValueError("invalid json"))
    )
    state = {"conversation_id": "c", "room_id": "r", "user_id": "u", "message_id": 123}
    kwargs = (
        {"intent": "place_order_request", "order_list": []}
        if target == "swap"
        else {
            "intent": "new_inquiry",
            "order_list": [],
        }
        if target == "option"
        else {"intent": "close_order_request", "close_order_req_vo": {}}
    )
    with pytest.raises(BackendUnreachableError):
        await getattr(module, f"call_{target}_backend")(state, **kwargs)


def test_retry_900_scope_excludes_quick_inquiry():
    from app.api.notifications import project_retry_notification

    response = {
        "answer": "重复通知",
        "data": {"outputs": {"api_code": 900, "api_result": "重复通知"}},
    }
    ordinary = project_retry_notification(response, {"retry_origin": "XBOT_GET_DIFY_FAIL"})
    assert ordinary["answer"] == "IGNORE_REQUEST_NOT_REPLY_USER"
    assert ordinary["data"]["outputs"]["api_result"] == "重复通知"
    assert (
        project_retry_notification(
            response, {"retry_origin": "XBOT_GET_DIFY_FAIL", "fast_query": "1"}
        )
        == response
    )


async def test_batch_500_with_no_message_uses_service_unavailable_reply(monkeypatch):
    from unittest.mock import MagicMock

    from app.execution import operations
    from app.graph.instructions import build_instructions_graph
    from app.subgraphs.swap.backend import call_swap_backend

    class Worker:
        async def ainvoke(self, state, config=None, **kwargs):
            await call_swap_backend(state, intent="place_order_request", order_list=[{}])
            return state

    monkeypatch.setattr(
        operations,
        "SwapClientHttpx",
        lambda: MagicMock(operate=AsyncMock(return_value={"code": 500})),
    )
    result = await build_instructions_graph(Worker()).ainvoke(
        {
            "raw_text": "买甲",
            "conversation_id": "c",
            "user_id": "u",
            "room_id": "r",
            "message_id": 123,
            "sub_instructions": [
                {"text": "买甲", "evidence": "买甲", "start": 0, "end": 2, "confidence": 1}
            ],
        }
    )
    assert "交易指令服务暂不可用" in result["reply_text"]
    assert result["instruction_results"][0]["api_code"] == 500


async def test_quick_parser_invalid_response_uses_business_copy_without_losing_reason():
    import httpx

    from app.tools.goats_agent_client import GoatsAgentClientHttpx
    agent = GoatsAgentClientHttpx("http://goats.invalid", "C", "S", "X",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="invalid-json")))
    result = await agent.parse_rfq_instrument("快速询价", "room", "user")
    assert result["errMsg"] == "快速询价暂不可用,请检查网络"
    assert result["reason"] == "invalid_json"
