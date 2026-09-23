"""真实提取、字段锁与 HTTP 序列化必须保留每笔订单的范围和参数。"""
import json

import httpx
import pytest

from app.subgraphs.option.extract_cancel import option_extract_cancel
from app.subgraphs.option.extract_confirm_place import option_extract_confirm_place
from app.subgraphs.option.extract_place import option_extract_place
from app.tools.option_client import OptionClientHttpx

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


@pytest.mark.parametrize("raw", [
    "序号1限价10，序号2限价20，确认下单",
    "确认下单，序号1限价10，序号2限价20",
])
async def test_confirmation_keeps_individual_prices(requests, raw):
    result = await option_extract_confirm_place(state(raw))
    assert not result.get("error"), result
    assert [(o["orderId"], float(o["limitPrice"])) for o in requests[0]["orderList"]] == [
        (FIRST, 10), (SECOND, 20)]
    second = result["field_records"]["option/confirm_place.orderList.1.limitPrice"]
    assert "限价20" in second.evidence and "限价10" not in second.evidence


async def test_explicit_ids_bind_different_execution_parameters(requests):
    await option_extract_place(state(f"{FIRST} 100万市价，{SECOND} 200万限价10"))
    assert [(o["orderId"], str(o["notionalAmount"]), o["orderType"])
            for o in requests[0]["orderList"]] == [
        (FIRST, "1000000", "市价单"), (SECOND, "2000000", "限价单")]


@pytest.mark.parametrize("raw,expected", [
    ("序号2限价10", FIRST), ("第二笔限价10", SECOND),
])
async def test_displayed_sequence_and_position_are_distinct(requests, raw, expected):
    await option_extract_place(state(raw, f"序号2：{FIRST}\n序号4：{SECOND}"))
    assert [o["orderId"] for o in requests[0]["orderList"]] == [expected]


@pytest.mark.parametrize("raw,expected", [
    ("第2笔，确认下单", SECOND), ("第2笔限价10，确认下单", SECOND),
    ("序号2限价10，确认下单", FIRST),
])
async def test_confirmation_uses_the_same_position_and_label_semantics(requests, raw, expected):
    await option_extract_confirm_place(state(raw, f"序号2：{FIRST}\n序号4：{SECOND}"))
    assert len(requests) == 1
    assert [o["orderId"] for o in requests[0]["orderList"]] == [expected]


async def test_explicit_shared_parameters_and_local_overrides(requests):
    await option_extract_place(state("全部100万市价，第二笔限价10"))
    assert [(o["orderId"], str(o["notionalAmount"]), o["orderType"])
            for o in requests[0]["orderList"]] == [
        (FIRST, "1000000", "市价单"), (SECOND, "1000000", "限价单")]


@pytest.mark.parametrize("raw", [
    "第3笔限价10", "第1笔限价10，第1笔限价20", "第一笔限价10，限价20",
    "100万，第一笔限价10，第二笔限价20",
])
async def test_ambiguous_parameters_never_partially_submit(requests, raw):
    result = await option_extract_place(state(raw))
    assert not requests
    assert result.get("reply_text")


@pytest.mark.parametrize("raw,ids", [
    ("撤掉第二笔", [SECOND]), ("撤序号2", [SECOND]),
    ("撤第一笔、第二笔", [FIRST, SECOND]),
    ("撤单", [FIRST, SECOND]), ("全部撤单", [FIRST, SECOND]),
    (f"撤单 {FIRST}", [FIRST]),
])
async def test_cancel_respects_selection_and_keeps_default_all(requests, raw, ids):
    await option_extract_cancel(state(raw))
    assert [o["orderId"] for o in requests[0]["orderList"]] == ids


@pytest.mark.parametrize("raw", [
    "撤第三笔", "撤序号0", "撤序号-1", "除了第二笔全部撤", "撤最后几笔",
    "撤前两笔", "撤第一、第二笔", "撤掉1、2", "第二笔不要撤",
])
async def test_unresolved_cancel_scope_never_defaults_to_all(requests, raw):
    result = await option_extract_cancel(state(raw))
    assert not requests
    assert result.get("reply_text")


async def test_single_explicit_order_can_follow_its_parameters(requests):
    await option_extract_place(state(f"100万市价 {SECOND}"))
    row = requests[0]["orderList"][0]
    assert row["orderId"] == SECOND and str(row["notionalAmount"]) == "1000000"


@pytest.mark.parametrize("node,raw", [
    (option_extract_cancel, f"撤序号1 {SECOND}"),
    (option_extract_place, f"序号1 {SECOND} 限价10"),
])
async def test_conflicting_adjacent_id_and_sequence_never_submit(requests, node, raw):
    result = await node(state(raw))
    assert not requests and result.get("reply_text")


async def test_shared_fast_execution_and_specific_ratio_stay_per_order(requests):
    await option_extract_place(state("全部最大跟量100万，第二笔POV25限价10"))
    first, second = requests[0]["orderList"]
    assert first["hasFastExecutionIntent"] is True
    assert second["hasFastExecutionIntent"] is False and float(second["povRatio"]) == 25


@pytest.mark.parametrize("raw", ["第一笔100万，200万市价", "第一笔POV10，POV20"])
async def test_conflicting_amount_or_ratio_stops_before_http(requests, raw):
    result = await option_extract_place(state(raw))
    assert not requests and result.get("reply_text")
