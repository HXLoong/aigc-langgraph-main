"""撤单范围通过真实节点、DTO 和 HTTP 请求验证。"""
from __future__ import annotations

import json

import httpx
import pytest

from app.nodes.render import render
from app.subgraphs.swap import backend
from app.subgraphs.swap.cancel import swap_cancel
from app.tools.swap_client import SwapClientHttpx

FIRST = "H-20260915-0000000001"
SECOND = "H-20260915-0000000002"
QUOTE = f"""1. -----场外收益互换详情-----
单号：{FIRST}
大合约编号：CONTRACT-A
标的代码：600519.SH
标的名称：贵州茅台
2. -----场外收益互换详情-----
单号：{SECOND}
大合约编号：CONTRACT-B
标的代码：000858.SZ
标的名称：五粮液
"""


@pytest.fixture
def cancel_requests(monkeypatch):
    requests = []

    def handle(request):
        assert request.method == "POST"
        assert request.url.path == "/admin-api/swap-order/operate"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "撤单请求已受理"})

    monkeypatch.setattr(backend, "SwapClientHttpx", lambda: SwapClientHttpx(
        base_url="http://cancel.test", token="test-only", dry_run=False,
        transport=httpx.MockTransport(handle),
    ))
    return requests


def cancel_state(raw, quote=QUOTE):
    return {
        "raw_text": raw, "quote_content": quote, "product_type": "swap",
        "intent": "cancel_order_request", "conversation_id": "cancel-scope",
        "room_id": "test-room", "user_id": "test-user", "message_id": "123",
        "cancel_params": {"orderList": [{"orderId": SECOND}]},
    }


async def test_cancel_first_order_only(cancel_requests):
    state = cancel_state("撤第一笔")
    result = await swap_cancel(state)
    assert not result.get("error")
    assert result["cancel_params"]["orderList"] == [{"orderId": FIRST}]
    assert len(cancel_requests) == 1
    assert cancel_requests[0]["type"] == "cancel_order_request"
    assert cancel_requests[0]["orderList"] == [{"orderId": FIRST}]
    assert (await render({**state, **result}))["reply_text"] == "撤单请求已受理"


@pytest.mark.parametrize("raw,quote,expected", [
    ("撤第2笔", QUOTE, [SECOND]),
    ("撤第二笔", QUOTE.replace("1. ", "8. "), [SECOND]),
    ("撤第八笔", QUOTE.replace("1. ", "8. "), [FIRST]),
    ("撤第一笔", QUOTE.replace("1. ", "").replace("2. ", ""), [FIRST]),
    ("撤第八笔", QUOTE.replace("1. ", "8.\n"), [FIRST]),
    ("撤第八笔", f"单号：{FIRST}\n序号：8\n标的代码：600519.SH", [FIRST]),
    ("撤第八笔", f"订单{FIRST}(序号8)\n订单{SECOND}(序号2)", [FIRST]),
    ("撤序号8", f"序号：8\n单号：{FIRST}\n序号：2\n单号：{SECOND}", [FIRST]),
    ("撤600519.SH", f"单号：{FIRST} 标的代码：600519.SH\n单号：{SECOND} 标的代码：000858.SZ", [FIRST]),
    ("撤600519.SH", f"单号：{FIRST} 标的代码：600519.SH 单号：{SECOND} 标的代码：000858.SZ", [FIRST]),
    ("撤序号2", QUOTE, [SECOND]),
    ("撤600519.SH", QUOTE, [FIRST]),
    ("撤贵州茅台", QUOTE, [FIRST]),
    ("撤合约CONTRACT-B", QUOTE, [SECOND]),
    ("撤第二笔五粮液，合约CONTRACT-B", QUOTE, [SECOND]),
    (f"撤{SECOND}，合约CONTRACT-B", QUOTE, [SECOND]),
    (f"撤{FIRST}", "", [FIRST]),
    ("全部撤单", QUOTE, [FIRST, SECOND]),
    ("全部撤单", QUOTE + QUOTE, [FIRST, SECOND]),
    ("撤贵州茅台", QUOTE.replace("000858.SZ", "600519.SH").replace("五粮液", "贵州茅台"), [FIRST, SECOND]),
    ("撤单", "", [None]),
])
async def test_cancel_scope_reaches_backend_without_expanding(cancel_requests, raw, quote, expected):
    result = await swap_cancel(cancel_state(raw, quote))
    assert not result.get("error"), result.get("error")
    orders = [{"orderId": value} for value in expected]
    assert result["cancel_params"]["orderList"] == orders
    assert len(cancel_requests) == 1
    assert cancel_requests[0]["orderList"] == ([{}] if expected == [None] else orders)


@pytest.mark.parametrize("raw,quote", [
    ("撤第三笔", QUOTE),
    ("撤第一笔", ""),
    ("撤第一笔", QUOTE.replace("1. ", "8. ")),
    ("撤第一笔五粮液", QUOTE),
    ("撤第一笔合约CONTRACT-B", QUOTE),
    (f"撤{FIRST}，合约CONTRACT-B", QUOTE),
    (f"撤{FIRST}，合约CONTRACT-A", ""),
    ("撤600519.SH", ""),
    ("撤不存在的标的", QUOTE),
    ("撤最后面那个", QUOTE),
    ("撤H-20260915-123", QUOTE),
    ("撤合约UNKNOWN", QUOTE),
    ("撤合约", QUOTE),
    ("撤标的", QUOTE),
    ("撤H-20260915-000000000199", QUOTE),
])
async def test_unresolved_cancel_scope_clears_params_and_never_calls_backend(cancel_requests, raw, quote):
    state = cancel_state(raw, quote)
    result = await swap_cancel(state)
    assert cancel_requests == []
    assert result["cancel_params"] is None
    assert not result.get("error"), result.get("error")
    state.update(result)
    state.update(await render(state))
    reply = state["reply_text"]
    assert "订单号" in reply and "重新引用" in reply
