"""跨产品动态单号只绑定上一轮实际回复中的唯一业务订单。"""
import pytest

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
