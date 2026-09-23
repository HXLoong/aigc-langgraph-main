"""跨产品动态单号只绑定上一轮实际回复中的唯一业务订单。"""
import httpx
import pytest

from harness.golden import GoldenCase
from harness.multi_turn import run_case_multi
from harness.scenario_inputs import resolve_order_reference


def test_previous_order_id_accepts_real_swap_receipt():
    reply = '互换订单H-20260923-1119033856：订单处理中，请稍候。'
    assert resolve_order_reference('撤单 {{previous_order_id}}', reply) == '撤单 H-20260923-1119033856'


@pytest.mark.parametrize('reply', [
    '互换订单H-20260923-1；期权订单Q-20260923-2',
    '互换订单H-20260923-1；互换订单H-20260923-2',
    '未生成订单',
])
def test_previous_order_id_does_not_guess_across_products_or_orders(reply):
    with pytest.raises(ValueError):
        resolve_order_reference('撤单 {{previous_order_id}}', reply)


def test_holding_reference_uses_explicit_position_in_previous_card():
    reply = ('以下是您的期权持仓\n序号：8\n合约编号：OPT-TEST2401\n'
             '序号：20\n合约编号：OPTG-TEST2402\n'
             '例如：\n合约编号：OPT-EXAMPLE\n')
    assert resolve_order_reference(
        '我想平掉 {{previous_holding_contract_id:2}}', reply,
    ) == '我想平掉 OPTG-TEST2402'


@pytest.mark.parametrize('placeholder,reply', [
    ('{{previous_holding_contract_id}}', '合约编号：OPT-ONE\n合约编号：OPT-TWO'),
    ('{{previous_holding_contract_id:1}}', '没有可平持仓'),
    ('{{previous_holding_contract_id:1}}', '例如：\n合约编号：OPT-EXAMPLE'),
    ('{{previous_holding_contract_id:2}}', '合约编号：OPT-ONE'),
    ('{{previous_holding_contract_id:0}}', '合约编号：OPT-ONE'),
    ('{{previous_holding_contract_id:-1}}', '合约编号：OPT-ONE'),
    ('{{previous_holding_contract_id:abc}}', '合约编号：OPT-ONE'),
])
def test_holding_reference_cannot_guess_or_send_unresolved_placeholder(placeholder, reply):
    with pytest.raises(ValueError):
        resolve_order_reference('我想平掉 ' + placeholder, reply)


async def test_missing_live_holding_stops_before_write_as_fixture_precondition():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {
            "reply_text": "暂无符合平仓条件的期权合约。", "product_type": "option_close",
            "intent": "close_order_query", "api_code": 0,
        }}})

    case = GoldenCase(id="live-holding", category="option_close", turns=[
        {"send_text": "查可平持仓"},
        {"send_text": "我想平掉 {{previous_holding_contract_id:1}}", "quote_previous": True},
    ])
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r",
                                     client=client)
    assert len(requests) == 1
    assert result.failure["kind"] == "fixture_precondition"
    assert result.remaining_turns == 1
