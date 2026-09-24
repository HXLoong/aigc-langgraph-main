"""Java/GOATS 后端响应透传契约（2026-09 决定）。

后端返回的数据一律**原样 dict 透传**：客户端层只做 HTTP + JSON 解析 +
CommonResult 信封解包（`data` 字段），不做 Pydantic 建模 / 字段校验。
缺失字段、类型异常、未知字段都必须原封不动传给调用方。
"""
from __future__ import annotations

import httpx
import pytest

from app.tools.message_client import (
    MessageClientHttpx,
    SetIntentRequest,
)
from app.tools.option_client import (
    FinancialOrderOpenApiSaveReqVO,
    OptionClientHttpx,
    OptionIntentionType,
)
from app.tools.ticker_client import TickerClientHttpx


def _option_request() -> FinancialOrderOpenApiSaveReqVO:
    return FinancialOrderOpenApiSaveReqVO(
        type=OptionIntentionType.NEW_INQUIRY,
        conversationId="c-1",
        messageId=1,
        messageContent="m",
        rawContent="r",
        userId="u",
        roomId="room-1",
    )


def _option_client(handler: object) -> OptionClientHttpx:
    return OptionClientHttpx(
        base_url="https://java.invalid", token="",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        dry_run=False,
    )


async def test_option_operate_returns_raw_backend_envelope() -> None:
    """含未知字段的信封原样返回（不建模型、不丢字段）。"""
    envelope = {
        "code": 0, "msg": "ok", "data": {"orderId": "H-1"}, "requestId": "trace-1",
    }
    client = _option_client(lambda request: httpx.Response(200, json=envelope))
    result = await client.operate(_option_request())
    assert result == envelope


async def test_option_operate_odd_types_pass_through() -> None:
    """后端字段类型异常（code 字符串 / msg=None / data 嵌套列表）不触发校验错误。"""
    envelope = {"code": "0", "msg": None, "data": [{"nested": True}]}
    client = _option_client(lambda request: httpx.Response(200, json=envelope))
    result = await client.operate(_option_request())
    assert result == envelope


async def test_ticker_list_counterparty_passthrough() -> None:
    rows = [{"ctptyId": "1", "shortName": "测试对手", "groupFlag": False}]
    client = TickerClientHttpx(
        base_url="https://java.invalid", token="",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 0, "data": rows})
        ),
    )
    result = await client.list_counterparty(room_id="r-1")
    assert result == rows


async def test_message_set_intent_returns_raw_payload() -> None:
    """ACK 成功时返回原始信封（含未知字段），不做模型转换。"""
    payload = {"code": 0, "msg": "ok", "data": True, "serverTime": 123}
    client = MessageClientHttpx(
        base_url="https://java.invalid", token="",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload)
        ),
    )
    request = SetIntentRequest(
        conversationId="c-1", messageId="42", intent="new_inquiry", productType=0,
    )
    result = await client.set_intent(request)
    assert result == payload


@pytest.mark.parametrize("code", [0, 987])
async def test_message_set_intent_ack_guard_still_reads_code(code: int) -> None:
    """写回 ACK 校验保留在原始 dict 上：code=0 通过，business code 抛业务错误。"""
    from app.tools.message_client import SetIntentError

    client = MessageClientHttpx(
        base_url="https://java.invalid", token="",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": code, "msg": "m"})
        ),
    )
    request = SetIntentRequest(
        conversationId="c-1", messageId="42", intent="new_inquiry", productType=0,
    )
    if code == 0:
        assert (await client.set_intent(request))["code"] == 0
    else:
        with pytest.raises(SetIntentError, match="^set-intent: business_error$"):
            await client.set_intent(request)
