"""真实提取、字段锁与 HTTP 序列化必须保留每笔订单的范围和参数。"""
import json

import httpx
import pytest

from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.extract_place import option_extract_place
from app.tools.option_client import OptionClientHttpx
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes

FIRST = "Q-20260922-0000000001"
SECOND = "Q-20260922-0000000002"
QUOTE = f"序号1：{FIRST}\n期限：1M\n序号2：{SECOND}\n期限：2M"


def state(raw, quote=QUOTE):
    return {"raw_text": raw, "quote_content": quote, "conversation_id": "scope-test",
            "message_id": 1, "room_id": "test-room", "user_id": "test-user"}


@pytest.fixture
def requests(monkeypatch):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": "后端原始回执"})

    client = OptionClientHttpx(base_url="http://java.test", token="test",
                              transport=httpx.MockTransport(handler), dry_run=False)
    monkeypatch.setattr("app.subgraphs.option.backend.OptionClientHttpx", lambda: client)
    return sent














@pytest.mark.parametrize("raw,ids", [
    ("撤掉第二笔", [SECOND]), ("撤序号2", [SECOND]),
    ("撤第一笔、第二笔", [FIRST, SECOND]),
    ("撤单", [FIRST, SECOND]), ("全部撤单", [FIRST, SECOND]),
    (f"撤单 {FIRST}", [FIRST]),
])
async def test_cancel_respects_selection_and_keeps_default_all(requests, raw, ids):
    await run_request_nodes(option_extract_cancel, state(raw), "option")
    assert [o["orderId"] for o in requests[0]["orderList"]] == ids


@pytest.mark.parametrize("raw", [
    "撤第三笔", "撤序号0", "撤序号-1", "除了第二笔全部撤", "撤最后几笔",
    "撤前两笔", "撤第一、第二笔", "撤掉1、2", "第二笔不要撤",
])
async def test_unresolved_cancel_scope_never_defaults_to_all(requests, raw):
    result = await run_request_nodes(option_extract_cancel, state(raw), "option")
    assert not requests
    assert result.get("reply_text")











@pytest.mark.parametrize("raw,expected", [
    ("序号2限价10", FIRST), ("第二笔限价10", SECOND),
    ("第2笔限价10，确认下单", SECOND), ("序号2限价10，确认下单", FIRST),
])
async def test_current_quote_labels_and_positions_are_distinct(requests, raw, expected):
    """同一组引用的序号标签与位置不能混用，接口只发送选中的单。"""
    quote = f"序号2：{FIRST}\n序号4：{SECOND}"
    intent = "confirm_order" if "确认" in raw else "place_order_from_quote"
    orders = [{"orderId": expected, "limitPrice": 10}]
    node = option_extract_confirm_place if intent == "confirm_order" else option_extract_place
    result = await run_request_nodes(node, {**state(raw, quote), "parsed_instruction": instruction_data(
        "option", intent, raw, orders=orders, quote=quote)}, "option")
    assert not result.get("error"), result
    assert requests[0]["orderList"] == orders


async def test_two_selected_orders_keep_their_own_explicit_prices(requests):
    """批次字段与原文分别绑定，后端序列化不交换订单值。"""
    raw = "序号1限价10，序号2限价20，确认下单"
    orders = [{"orderId": FIRST, "limitPrice": 10}, {"orderId": SECOND, "limitPrice": 20}]
    parsed = instruction_data("option", "confirm_order", raw, orders=orders, quote=QUOTE)
    for record in parsed["fields"]:
        if record["path"].endswith("limitPrice"):
            record["text"] = "序号1限价10" if ".0." in record["path"] else "序号2限价20"
    result = await run_request_nodes(option_extract_confirm_place, {**state(raw), "parsed_instruction": parsed}, "option")
    assert not result.get("error"), result
    assert requests[0]["orderList"] == orders
    assert result["field_records"]["option/parse.orderList.1.limitPrice"].evidence == "序号2限价20"
