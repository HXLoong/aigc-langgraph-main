"""Swap 子图 backend 集成单测（Issue #79）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.swap import backend as backend_mod
from app.subgraphs.swap.backend import (
    _message_id,
    _with_resolved_ticker,
    call_swap_backend,
)
from app.tools.exceptions import BackendUnreachableError
from app.tools.models import CommonResult


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
# _with_resolved_ticker
# ============================================================


def test_with_resolved_ticker_writes_wind_code() -> None:
    ticker = MagicMock()
    ticker.windCode = "600519.SH"
    order: dict = {}
    result = _with_resolved_ticker(order, [ticker], 0)
    assert result["placeOrderWindCode"] == "600519.SH"


def test_with_resolved_ticker_out_of_range_noop() -> None:
    order: dict = {"existing": 1}
    result = _with_resolved_ticker(order, [], 0)
    assert result == {"existing": 1}


def test_with_resolved_ticker_dict_ticker() -> None:
    order: dict = {}
    result = _with_resolved_ticker(order, [{"windCode": "00700.HK"}], 0)
    assert result["placeOrderWindCode"] == "00700.HK"


def test_with_resolved_ticker_no_wind_code_noop() -> None:
    ticker = MagicMock(spec=[])  # 没 windCode 属性
    order: dict = {"existing": 1}
    result = _with_resolved_ticker(order, [ticker], 0)
    assert result == {"existing": 1}


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
async def test_call_swap_backend_missing_context_returns_empty() -> None:
    """state 缺 conversation/room/user_id → 不调真后端（fail-safe）。"""
    result = await call_swap_backend({"raw_text": "x"}, intent="place_order_request")
    assert result == {}


@pytest.mark.asyncio
async def test_call_swap_backend_ok_returns_api_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value=CommonResult(code=0, msg="ok", data={"orderId": "S001"})
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    result = await call_swap_backend(
        _full_state(),
        intent="place_order_request",
        order_list=[{"placeOrderQuantity": 1000}],
    )
    assert result["api_code"] == 0
    assert result["api_result"] == {"orderId": "S001"}


@pytest.mark.asyncio
async def test_call_swap_backend_business_reject_returns_msg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """code != 0 → api_result = msg（透传错误信息给 render）。"""
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value=CommonResult(code=400, msg="缺少必填字段", data=None)
    )
    monkeypatch.setattr(backend_mod, "SwapClientHttpx", lambda: fake_client)

    result = await call_swap_backend(_full_state(), intent="place_order_request")
    assert result["api_code"] == 400
    assert result["api_result"] == "缺少必填字段"


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
        return_value=CommonResult(code=0, msg="ok", data=None)
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
# ============================================================


@pytest.mark.asyncio
async def test_place_order_node_writes_api_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """swap_place_order 节点端到端：state 含上下文 → 调真客户端 → api_code 写回。"""
    from app.subgraphs.swap import place_order as po_module
    from app.subgraphs.swap.models import SwapPlaceOrderParams, SwapOrderItem

    # mock LLM
    params = SwapPlaceOrderParams(
        orderList=[SwapOrderItem(placeOrderWindCode="腾讯", placeOrderQuantity=1000)]
    )
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(po_module, "get_qwen_structured", lambda: fake_base)

    # mock SwapClient
    fake_client = MagicMock()
    fake_client.operate = AsyncMock(
        return_value=CommonResult(code=0, msg="ok", data={"orderId": "S001"})
    )
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
    assert result["api_code"] == 0
    assert result["api_result"] == {"orderId": "S001"}
    assert result["place_params"]["expected_action"] == "place"
