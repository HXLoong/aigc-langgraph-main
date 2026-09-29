"""业务标注必须同时符合当前输入和实际增量更新契约。"""
from pathlib import Path

from app.subgraphs.option.models import OptionPlaceParams
from app.subgraphs.option.request_params import request_orders
from harness.differ import check_structured_assertions
from harness.golden import load_golden
from tests.joint_support import instruction_data


def test_case028_pov_change_accepts_partial_payload_and_rejects_wrong_ratio():
    case = next(case for case in load_golden(
        Path("tests/datasets/biz/option_open.jsonl"),
    ) if case.id == "case-028")
    turn = case.turns[2]
    quote = (
        "-----场外期权询价详情-----\n单号：Q-20260924-0000000001\n"
        "期权类型：欧式看涨\n标的代码：600519.SH\n期限：1M\n行权价格：80%\n"
        "名义本金：250万\n建仓方式：POV\nPOV比例：11%\n限定价格：10\n"
    )
    params = OptionPlaceParams.model_validate({
        "orderList": request_orders({"raw_text": turn.send_text, "quote_content": quote,
            "parsed_instruction": instruction_data("option", "place_order_from_quote", turn.send_text,
                orders=[{"orderId": "Q-20260924-0000000001", "povRatio": 12, "orderType": "POV"}], quote=quote)},
            "place_order_from_quote")[0],
    }).model_dump()
    output = {"product_type": "option", "intent": "place_order_from_quote",
              "place_params": params}
    assert not check_structured_assertions(output, turn.expected, quote_content=quote)
    params["orderList"][0]["povRatio"] = 11
    assert any(diff.path.endswith("povRatio") for diff in check_structured_assertions(
        output, turn.expected, quote_content=quote,
    ))
