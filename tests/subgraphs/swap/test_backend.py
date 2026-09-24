"""Swap 子图 backend 集成单测。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import backend as backend_mod
from app.subgraphs.swap.backend import (
    _message_id,
    call_swap_backend,
)
from app.tools.exceptions import (
    BackendUnreachableError,
    EmptyBackendResultError,
    MissingBackendContextError,
)
from tests.evidence_support import swap_candidate_output

# ============================================================
# _message_id
# ============================================================


def test_message_id_int_passthrough() -> None:
    assert _message_id(12345) == 12345


def test_message_id_digit_string() -> None:
    assert _message_id("msg-99887766") == 99887766


def test_message_id_no_digits_returns_zero() -> None:
    assert _message_id("no-digits-here") == 0


# ============================================================
# call_swap_backend
# ============================================================


def _full_state() -> dict:
    return {
        "raw_text": "互换下单 腾讯 1000 股",
        "conversation_id": "c1",
        "message_id": 100,
        "user_id": "u1",
        "room_id": "r1",
    }


@pytest.mark.asyncio
async def test_call_swap_backend_missing_context_raises_explicit_error() -> None:
    """缺机器人上下文时不得静默跳过后端并伪造业务回复。"""
    with pytest.raises(MissingBackendContextError) as exc_info:
        await call_swap_backend({"raw_text": "x"}, intent="place_order_request")

    assert exc_info.value.target == "swap"
    assert exc_info.value.missing_fields == (
        "conversation_id",
        "room_id",
        "user_id",
        "message_id",
    )


@pytest.mark.asyncio
async def test_call_swap_backend_ok_returns_api_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = "-----互换下单确认-----\n新单号: H-20260910-0000000001"
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value={"code": 0, "msg": "ok", "data": card}
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    result = await call_swap_backend(
        _full_state(),
        intent="place_order_request",
        order_list=[{"placeOrderQuantity": 1000}],
    )
    assert result == {"api_code": 0, "api_result": card}


@pytest.mark.asyncio
async def test_call_swap_backend_business_reject_returns_msg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """code != 0 → api_result = msg（透传错误信息给 render）。"""
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value={"code": 400, "msg": "缺少必填字段", "data": None}
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    result = await call_swap_backend(_full_state(), intent="place_order_request")
    assert result["api_code"] == 400
    assert result["api_result"] == "缺少必填字段"


@pytest.mark.asyncio
async def test_call_swap_backend_empty_result_raises_explicit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功码携带空 data 时不得回落到本地业务回复。"""
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value={"code": 0, "msg": "ok", "data": ""}
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    with pytest.raises(EmptyBackendResultError) as exc_info:
        await call_swap_backend(_full_state(), intent="place_order_request")

    assert exc_info.value.target == "swap"
    assert exc_info.value.code == 0


@pytest.mark.asyncio
async def test_call_swap_backend_unreachable_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BackendUnreachableError 应继续向上抛，由 @safe_node 捕获。"""
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        side_effect=BackendUnreachableError("swap", "timeout")
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    with pytest.raises(BackendUnreachableError) as exc_info:
        await call_swap_backend(_full_state(), intent="place_order_request")
    assert exc_info.value.target == "swap"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    [
        "place_order_request",
        "confirm_order",
        "cancel_order_request",
        "confirm_cancel_order",
        "confirm_modify_order",
        "query_order_status",
    ],
)
async def test_call_swap_backend_supports_all_swap_intents(
    monkeypatch: pytest.MonkeyPatch, intent: str
) -> None:
    """6 个 SwapIntentionType 都能正常构造请求。"""
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value={"code": 0, "msg": "ok", "data": "backend reply"}
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    result = await call_swap_backend(_full_state(), intent=intent)
    assert result["api_code"] == 0
    # 验证 SwapClient.operate 被调用，且 req.type 是预期的 intent
    fake_client.operate.assert_awaited_once()
    req = fake_client.operate.await_args[0][0]
    assert req.type.value == intent


# ============================================================
# 节点端到端：mock LLM + mock SwapClient
#
# DSL v2 拆分后，后端提交从 swap_place_order 移到独立的
# swap_place_order_submit 节点（swap.place_order 只做提取，见
# app/subgraphs/swap/place_order.py 模块 docstring）。
# ============================================================


@pytest.mark.asyncio
async def test_place_order_submit_node_writes_api_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """swap_place_order_submit 节点：state['place_params'] 就绪 → 调真客户端 → api_code 写回。"""
    from app.subgraphs.swap import place_order as po_module

    card = "-----互换下单确认-----\n新单号: H-20260910-0000000001"
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value={"code": 0, "msg": "ok", "data": card}
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    result = await po_module.swap_place_order_submit(
        {
            "place_params": {
                "orderList": [
                    {"placeOrderWindCode": "00700.HK", "placeOrderQuantity": 1000}
                ],
            },
            "conversation_id": "c1",
            "message_id": 100,
            "user_id": "u1",
            "room_id": "r1",
        }
    )
    assert result["api_code"] == 0
    assert result["api_result"] == card
    assert "expected_action" not in result["place_params"]
    assert "expected_action" not in result  # 提交节点不改写本轮动作
    # 后端返回真订单号 → 回写到 orderList[0].orderId，但不改写 api_result
    assert result["place_params"]["orderList"][0]["orderId"] == "H-20260910-0000000001"


@pytest.mark.asyncio
async def test_place_order_node_no_backend_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """swap_place_order 提取节点单独调用时不触发后端调用（职责已拆到 submit 节点）。"""
    from app.subgraphs.swap import place_order as po_module
    from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams

    params = SwapPlaceOrderParams(
        orderList=[SwapOrderItem(placeOrderWindCode="腾讯", placeOrderQuantity=1000)]
    )
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=swap_candidate_output(params))
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(po_module, "get_qwen_complex", lambda: fake_base)

    fake_client = MagicMock()
    fake_client.operate = AsyncMock(side_effect=AssertionError("不应调用后端"))
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    result = await po_module.swap_place_order(
        {
            "raw_text": "互换下单 腾讯 1000 股",
            "conversation_id": "c1",
            "message_id": 100,
            "user_id": "u1",
            "room_id": "r1",
        }
    )
    assert "api_code" not in result
    fake_client.operate.assert_not_called()
    assert result["expected_action"] == "place"
