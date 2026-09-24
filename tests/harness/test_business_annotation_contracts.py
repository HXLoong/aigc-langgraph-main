"""业务标注必须同时符合当前输入和实际增量更新契约。"""
from pathlib import Path

from app.subgraphs.option.models import OptionPlaceParams
from app.subgraphs.option.place_params import parse_place_params
from harness.differ import check_structured_assertions
from harness.golden import load_golden


def test_case028_pov_change_accepts_partial_payload_and_rejects_wrong_ratio():
    case = next(case for case in load_golden(
        Path("tests/fixtures/biz/option_open.jsonl"),
    ) if case.id == "case-028")
    turn = case.turns[2]
    quote = (
        "-----场外期权询价详情-----\n单号：Q-20260924-0000000001\n"
        "期权类型：欧式看涨\n标的代码：600519.SH\n期限：1M\n行权价格：80%\n"
        "名义本金：250万\n建仓方式：POV\nPOV比例：11%\n限定价格：10\n"
    )
    params = OptionPlaceParams.model_validate({
        "orderList": parse_place_params(turn.send_text, quote),
    }).model_dump()
    output = {"product_type": "option", "intent": "place_order_from_quote",
              "place_params": params}
    assert not check_structured_assertions(output, turn.expected, quote_content=quote)
    params["orderList"][0]["povRatio"] = 11
    assert any(diff.path.endswith("povRatio") for diff in check_structured_assertions(
        output, turn.expected, quote_content=quote,
    ))
