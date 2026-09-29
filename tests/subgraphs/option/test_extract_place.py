"""期权补参直接读取联合结果，不再本地解析语义或重建引用卡片。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option.extract_place import option_extract_place
from tests.joint_support import instruction_data

ORDER = "Q-20260922-0000000001"
QUOTE = f"单号：{ORDER}\n期限：1M\n标的：茅台\n名义本金：200万"


@pytest.mark.parametrize("raw,increment", [
    ("市价下单100万", {"orderType": "市价单", "notionalAmount": "1000000"}),
    ("POV7.5限价6.3", {"orderType": "POV", "povRatio": 7.5, "limitPrice": 6.3}),
    ("TWAP 9:30-15:00", {"orderType": "TWAP", "twapStartTime": "9:30", "twapEndTime": "15:00"}),
    ("最大跟量", {"hasFastExecutionIntent": True}),
    ("不要最大跟量", {"hasFastExecutionIntent": False}),
    ("期限改1Y", {"tenor": "1Y"}),
])
async def test_only_current_increment_is_submitted(monkeypatch, raw, increment):
    """接口装配不补未提到的旧字段，布尔 false 也按明确证据保留。"""
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "Java receipt"})
    monkeypatch.setattr("app.subgraphs.option.extract_place.prepare_option_request", backend)
    orders = [{"orderId": ORDER, **increment}]
    result = await option_extract_place({"raw_text": raw, "quote_content": QUOTE,
        "parsed_instruction": instruction_data("option", "place_order_from_quote", raw,
                                               orders=orders, quote=QUOTE)})
    assert not result.get("error"), result
    assert backend.await_args.kwargs["order_list"] == orders
    assert backend.await_args.kwargs["intent"] == "place_order_from_quote"
    assert result["api_result"] == "Java receipt"


async def test_missing_joint_result_cannot_submit(monkeypatch):
    """独立节点回放必须带实际解析输入，不能隐式重新调用模型。"""
    backend = AsyncMock()
    monkeypatch.setattr("app.subgraphs.option.extract_place.prepare_option_request", backend)
    result = await option_extract_place({"raw_text": "市价100万", "quote_content": QUOTE})
    assert result.get("error") and result["error"].code == "E2"
    backend.assert_not_called()
