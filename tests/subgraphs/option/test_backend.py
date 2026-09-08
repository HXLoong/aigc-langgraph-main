from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.observability import metrics
from app.subgraphs.option import backend as backend_module
from app.tools.exceptions import (
    EmptyBackendResultError,
    MissingBackendContextError,
)
from app.tools.models import CommonResult


@pytest.fixture(autouse=True)
def reset_metrics() -> None:
    metrics.get_collector().reset()
    yield
    metrics.get_collector().reset()


def _complete_state() -> dict[str, object]:
    return {
        "raw_text": "300773.SZ 拉卡拉，欧式看涨，1M，执行价80%",
        "conversation_id": "conversation-1",
        "message_id": 123,
        "user_id": "user-1",
        "room_id": "room-1",
    }


@pytest.mark.asyncio
async def test_missing_context_raises_and_does_not_call_backend(monkeypatch) -> None:
    client = MagicMock()
    client.operate = AsyncMock()
    monkeypatch.setattr(backend_module, "OptionClientHttpx", lambda: client)
    state = _complete_state()
    state.pop("room_id")

    with pytest.raises(MissingBackendContextError) as exc_info:
        await backend_module.call_option_backend(
            state, intent="new_inquiry", option_rfq={}
        )

    assert exc_info.value.missing_fields == ("room_id",)
    client.operate.assert_not_awaited()
    assert metrics.get_collector().get_counter(
        metrics.METRIC_OPTION_BACKEND_MISSING_CONTEXT_TOTAL
    ) == 1


@pytest.mark.asyncio
async def test_invalid_message_id_is_reported_as_missing_context(monkeypatch) -> None:
    client = MagicMock()
    client.operate = AsyncMock()
    monkeypatch.setattr(backend_module, "OptionClientHttpx", lambda: client)
    state = _complete_state()
    state["message_id"] = None

    with pytest.raises(MissingBackendContextError) as exc_info:
        await backend_module.call_option_backend(
            state, intent="new_inquiry", option_rfq={}
        )

    assert exc_info.value.missing_fields == ("message_id",)
    client.operate.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_context_logs_field_names_to_terminal(caplog) -> None:
    with (
        caplog.at_level(logging.ERROR, logger=backend_module.__name__),
        pytest.raises(MissingBackendContextError),
    ):
        await backend_module.call_option_backend(
            {"raw_text": "期权询价"},
            intent="new_inquiry",
            option_rfq={},
        )

    assert (
        "option backend call blocked: "
        "missing_fields=conversation_id,room_id,user_id,message_id"
    ) in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backend_response",
    [
        CommonResult(code=0, msg="ok", data=None),
        CommonResult(code=0, msg="ok", data="   "),
        CommonResult(code=0, msg="ok", data={}),
        CommonResult(code=0, msg="ok", data=[]),
        CommonResult(code=500, msg="", data=None),
    ],
)
async def test_empty_backend_result_raises_explicit_error(
    monkeypatch, backend_response: CommonResult
) -> None:
    client = MagicMock()
    client.operate = AsyncMock(return_value=backend_response)
    monkeypatch.setattr(backend_module, "OptionClientHttpx", lambda: client)

    with pytest.raises(EmptyBackendResultError):
        await backend_module.call_option_backend(
            _complete_state(), intent="new_inquiry", option_rfq={}
        )

    client.operate.assert_awaited_once()
    assert metrics.get_collector().get_counter(
        metrics.METRIC_OPTION_BACKEND_EMPTY_RESULT_TOTAL
    ) == 1


@pytest.mark.asyncio
async def test_nonempty_backend_card_is_returned_unchanged(monkeypatch) -> None:
    card = "-----场外期权询价详情-----\n单号：Q-1\n期限：1M"
    client = MagicMock()
    client.operate = AsyncMock(
        return_value=CommonResult(code=0, msg="ok", data=card)
    )
    monkeypatch.setattr(backend_module, "OptionClientHttpx", lambda: client)

    result = await backend_module.call_option_backend(
        _complete_state(), intent="new_inquiry", option_rfq={}
    )

    assert result == {"api_code": 0, "api_result": card}


@pytest.mark.asyncio
async def test_nonempty_backend_rejection_is_returned_unchanged(monkeypatch) -> None:
    rejection = "未找到标的信息"
    client = MagicMock()
    client.operate = AsyncMock(
        return_value=CommonResult(code=500, msg=rejection, data=None)
    )
    monkeypatch.setattr(backend_module, "OptionClientHttpx", lambda: client)

    result = await backend_module.call_option_backend(
        _complete_state(), intent="new_inquiry", option_rfq={}
    )

    assert result == {"api_code": 500, "api_result": rejection}
