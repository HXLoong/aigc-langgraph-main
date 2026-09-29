"""平仓字段映射不得隐含业务默认值或丢弃已提供参数。"""
from app.subgraphs.close.aggregate import build_close_order_req_vo


def test_no_business_defaults():
    """无参数时不主动限制可平仓范围。"""
    assert build_close_order_req_vo() == {}
    assert build_close_order_req_vo(closeable_only=False) == {"contractQuery": {"allowCloseOut": False}}


def test_only_current_action_fields_are_sent():
    """撤单不携带其它动作的空列表，原文值不清洗。"""
    assert build_close_order_req_vo(cancel_order_no_list=["CO-X"]) == {"cancelOrderNoList": ["CO-X"]}
    assert build_close_order_req_vo(underlying_ins_name_list=["null"]) == {"contractQuery": {"underlyingInsNameList": ["null"]}}
