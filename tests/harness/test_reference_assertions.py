"""结构断言绑定实际引用，不能用本轮输出反向生成 expected。"""
import copy

import httpx
import pytest

from harness.cli import _turn_diffs
from harness.differ import check_structured_assertions
from harness.golden import GoldenCase
from harness.multi_turn import run_case_multi

Q1 = "Q-20260923-0000000001"
Q2 = "Q-20260923-0000000002"
CO = "CO-20260923-00000001"
QUOTE = (
    f"-----场外期权询价详情-----\n序号：41\n单号：{Q1}\n"
    + "标的说明：" + "上下文" * 60
    + f"\n序号：90\n单号：{Q2}\nA. 甲对手（账户1）\nB. 乙对手（账户2）\n"
    + "例如：\n单号：Q-20260923-9999999999\n"
)


def test_bind_order_position_and_counterparty_without_mutating_expected():
    expected = {"place_params": {"orderList": [{
        "orderId": {"$ref": "quote.order_id", "position": 2},
        "shortName": {"$ref": "quote.counterparty", "option": "B"},
    }]}}
    before = copy.deepcopy(expected)
    actual = {"place_params": {"orderList": [{"orderId": Q2, "shortName": "乙对手（账户2）"}]}}
    assert not check_structured_assertions(actual, expected, quote_content=QUOTE)
    actual["place_params"]["orderList"][0]["orderId"] = Q1
    diffs = check_structured_assertions(actual, expected, quote_content=QUOTE)
    assert diffs[0].path == "place_params.orderList[0].orderId"
    assert diffs[0].expected == Q2
    assert expected == before


def test_bind_confirm_scope():
    assert not check_structured_assertions(
        {"confirm": {"confirmOrderNoList": [Q1, Q2]}},
        {"confirm": {"confirmOrderNoList": {"$ref": "quote.order_ids"}}},
        quote_content=QUOTE,
    )


def test_cancel_receipt_inline_order_number_is_a_reference():
    quote = f"期权平仓订单[{CO}]：已收到您的撤单请求，如需继续，请引用本消息回复【确认撤单】"
    assert not check_structured_assertions(
        {"confirm": {"confirmCancelOrderNoList": [CO]}},
        {"confirm": {"confirmCancelOrderNoList": {"$ref": "quote.order_ids"}}},
        quote_content=quote,
    )


def test_reference_cannot_replace_the_entire_expected_object():
    diffs = check_structured_assertions({}, {"$ref": "quote.order_ids"}, quote_content=QUOTE)
    assert diffs and diffs[0].path == "expected"


def test_bind_holding_contract_from_current_quote():
    quote = f"序号：8\n单号：{CO}\n合约编号：OPT-AAAA1\n"
    assert not check_structured_assertions(
        {"close_params": {"closeOrderList": [{"internalTradeId": "OPT-AAAA1"}]}},
        {"close_params": {"closeOrderList": [{
            "internalTradeId": {"$ref": "quote.holding_contract", "position": 1},
        }]}}, quote_content=quote,
    )


@pytest.mark.parametrize("reference,quote", [
    ({"$ref": "quote.order_id"}, ""),
    ({"$ref": "quote.order_id"}, QUOTE),
    ({"$ref": "quote.order_id", "position": 3}, QUOTE),
    ({"$ref": "quote.order_id", "position": 0}, QUOTE),
    ({"$ref": "quote.order_id", "position": True}, QUOTE),
    ({"$ref": "quote.counterparty", "option": "C"}, QUOTE),
    ({"$ref": "quote.counterparty", "option": "A"}, "A. 甲\nA. 乙"),
    ({"$ref": "quote.counterparty"}, QUOTE),
    ({"$ref": "quote.order_ids", "option": "A"}, QUOTE),
    ({"$ref": "outputs.orderId"}, QUOTE),
])
def test_missing_ambiguous_or_invalid_reference_cannot_pass(reference, quote):
    diffs = check_structured_assertions({"confirm": {"orderId": Q1}},
                                      {"confirm": {"orderId": reference}}, quote_content=quote)
    assert diffs
    assert diffs[0].path == "confirm.orderId"


@pytest.mark.parametrize("quote_previous", [True, False])
async def test_http_runner_uses_full_current_quote_not_preview_or_unquoted_history(quote_previous):
    calls = []
    def handler(request):
        calls.append(request)
        outputs = {"reply_text": QUOTE} if len(calls) == 1 else {
            "reply_text": "订单已受理", "confirm": {"orderList": [{"orderId": Q2}]},
        }
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": outputs}})

    case = GoldenCase(id="reference-scope", category="option", turns=[
        {"send_text": "询价"},
        {"send_text": "确认第二笔下单", "quote_previous": quote_previous, "expected": {
            "confirm": {"orderList": [{"orderId": {"$ref": "quote.order_id", "position": 2}}]},
        }},
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r", client=client)
    diffs = _turn_diffs(case, result)
    assert bool(diffs[2]) is (not quote_previous)
    if quote_previous:
        assert len(result.turns[1].quote_passed) == 120
        assert Q2 not in result.turns[1].quote_passed


def test_example_card_header_cannot_reintroduce_example_order_into_scope():
    quote = f"单号：{Q1}\n例如：\n-----场外期权询价详情-----\n单号：{Q2}"
    expected = {"confirm": {"ids": {"$ref": "quote.order_ids"}}}
    assert check_structured_assertions(
        {"confirm": {"ids": [Q1, Q2]}}, expected, quote_content=quote,
    )
    assert not check_structured_assertions(
        {"confirm": {"ids": [Q1]}}, expected, quote_content=quote,
    )


@pytest.mark.parametrize("quote_previous", [True, False])
async def test_any_turn_references_bind_to_that_turn_quote(quote_previous):
    calls = []
    def handler(request):
        calls.append(request)
        outputs = {"reply_text": f"单号：{Q1}"} if len(calls) == 1 else {
            "reply_text": "已受理", "confirm": {"orderId": Q1},
        }
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": outputs}})

    case = GoldenCase(id="any-turn-reference", category="option", expected_scope="any_turn",
                      expected={"confirm": {"orderId": {"$ref": "quote.order_id"}}}, turns=[
                          {"send_text": "询价"},
                          {"send_text": "确认下单", "quote_previous": quote_previous},
                      ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r", client=client)
    diffs = _turn_diffs(case, result)
    assert bool(diffs.get("case")) is (not quote_previous)
