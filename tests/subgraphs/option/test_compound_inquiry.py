"""模型完成组合语义，询价子图保留全部结果及对应原文证据。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes


@pytest.mark.parametrize("token,strike", [("100call", 100), ("80CALL", 80), ("97.5% CALL", 97.5), ("100看涨", 100)])
async def test_compound_values_and_original_evidence_reach_java(monkeypatch, token, strike):
    """不在子图再次分词或重算，保留模型给出的值和原始含义证据。"""
    client = AsyncMock(return_value={"code": 0, "data": "Java receipt"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", client)
    raw = f"宁德时代，{token}，1M/2M"
    orders = [{"stockCode": "宁德时代", "optionType": "欧式看涨", "strikePercentage": strike,
               "tenor": tenor} for tenor in ("1M", "2M")]
    parsed = instruction_data("option", "new_inquiry", raw, orders=orders)
    for field in parsed["fields"]:
        if field["path"].endswith(("optionType", "strikePercentage")):
            field["text"] = token
    result = await run_request_nodes(option_extract_inquiry, {"raw_text": raw, "conversation_id": "c", "message_id": 1,
        "user_id": "u", "room_id": "r", "parsed_instruction": parsed}, "option")
    assert not result.get("error"), result
    wire = client.await_args.args[0].model_dump(by_alias=True, exclude_none=True)
    assert wire["orderList"] == orders
    for index in range(2):
        record = result["field_records"][f"option/parse.orderList.{index}.strikePercentage"]
        assert record.value == strike and record.evidence == token and record.locked
