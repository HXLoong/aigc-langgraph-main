"""普通询价保持模型给出的全部订单与标的原文，证券校验归 Java。"""
from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option.extract_inquiry import option_extract_inquiry
from tests.joint_support import instruction_data
from tests.request_support import run_request_nodes


@pytest.mark.parametrize("names", [["600519.SH", "600519.SH"], ["茅台", "腾讯"], ["unknown", " 600519 "]])
async def test_all_orders_keep_original_security_expressions(monkeypatch, names):
    """即使前端兼容 tickers 有其它候选，也不替换本次原文或少提交订单。"""
    backend = AsyncMock(return_value={"code": 0, "data": "Java card"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    raw = "、".join(names) + "期权询价1M/2M"
    orders = [{"stockCode": name, "tenor": tenor} for name, tenor in zip(names, ("1M", "2M"), strict=True)]
    result = await run_request_nodes(option_extract_inquiry, {"raw_text": raw, "conversation_id": "c", "message_id": 1,
        "room_id": "r", "user_id": "u", "tickers": [{"windCode": "OTHER.O", "from_goats": True}],
        "parsed_instruction": instruction_data("option", "new_inquiry", raw, orders=orders)}, "option")
    assert not result.get("error"), result
    assert backend.await_args.args[0].model_dump(exclude_none=True)["orderList"] == orders
    assert result["place_params"]["orderList"] == orders


async def test_unspecified_security_is_not_filled_from_tickers(monkeypatch):
    """缺字段交 Java 提示，不能将唯一候选擅自当成用户选择。"""
    backend = AsyncMock(return_value={"code": 0, "data": "Java要求补充标的"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    result = await run_request_nodes(option_extract_inquiry, {"raw_text": "期权询价1M", "conversation_id": "c", "message_id": 1,
        "room_id": "r", "user_id": "u", "tickers": [{"windCode": "600519.SH"}],
        "parsed_instruction": instruction_data("option", "new_inquiry", "期权询价1M", orders=[{"tenor": "1M"}])}, "option")
    assert not result.get("error"), result
    assert backend.await_args.args[0].model_dump(exclude_none=True)["orderList"] == [{"tenor": "1M"}]
