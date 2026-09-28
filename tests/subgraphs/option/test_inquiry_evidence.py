"""询价保留接口数值和原文证据，缺来源时直接停止。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from tests.joint_support import instruction_data


@pytest.mark.parametrize("evidence,valid", [("100万", True), ("200万", False)])
async def test_amount_source_is_checked_without_recalculating_value(monkeypatch, evidence, valid):
    """金额接口值来自模型，代码只检查对应连续原文属于当前输入。"""
    backend = AsyncMock(return_value={"code": 0, "data": "Java card"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    raw = "茅台期权询价100万"
    parsed = instruction_data("option", "new_inquiry", raw, orders=[{"stockCode": "茅台", "notionalAmount": "1000000"}])
    parsed["fields"][1]["text"] = evidence
    result = await option_extract_inquiry({"raw_text": raw, "conversation_id": "c", "message_id": 1,
        "room_id": "r", "user_id": "u", "parsed_instruction": parsed})
    if valid:
        assert not result.get("error"), result
        record = result["field_records"]["option/parse.orderList.0.notionalAmount"]
        assert record.value == "1000000" and record.evidence == "100万" and record.locked
    else:
        assert result.get("error")
        backend.assert_not_called()
