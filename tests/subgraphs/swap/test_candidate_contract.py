"""The actual extraction request carries field boundaries without changing the wire DTO."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.subgraphs.swap import place_order
from app.subgraphs.swap.models import SwapOrderItem, SwapPlaceOrderParams

ORDER_ALIASES = (
    "orderId", "placeOrderUltraContractCode", "placeOrderWindCode",
    "placeOrderTransactionType", "placeOrderQuantity", "placeOrderQuantityHand",
    "placeOrderQuantityUnit", "placeOrderOrderDirection", "placeOrderPriceType",
    "placeOrderAlgorithmType", "placeOrderPrice", "placeOrderPovPercent",
    "placeOrderTotalPovPercent", "placeOrderDisplayQty", "placeOrderMaxVol",
    "placeOrderStartTime", "placeOrderEndTime", "placeOrderRelativeTimeMinutes",
    "placeOrderShortname", "placeOrderQuantityTotal", "placeOrderPremarket",
    "placeOrderNotional", "placeOrderNotionalCurrency", "placeOrderEntrustRatio",
    "placeOrderCloseIntent", "hasFastExecutionIntent",
)


def _tool_order_properties():
    tool = convert_to_openai_tool(place_order.CANDIDATE_MODEL)
    return tool["function"]["parameters"]["properties"]["orderList"]["items"]["properties"]


@pytest.mark.parametrize("alias,required_semantics", [
    ("placeOrderWindCode", ("单独名称", "单独代码", "数量", "交易对手")),
    ("placeOrderTransactionType", ("港股", "深港通", "不推断")),
    ("placeOrderOrderDirection", ("持仓范围", "数量正负", "null")),
    ("placeOrderPriceType", ("限价", "市价", "均价", "算法")),
    ("placeOrderAlgorithmType", ("POV", "TWAP", "VWAP", "风格", "不附带")),
    ("placeOrderStartTime", ("钟点", "HH:MM", "全天", "收盘", "不推算")),
    ("placeOrderEndTime", ("钟点", "HH:MM", "全天", "收盘", "不推算")),
    ("placeOrderRelativeTimeMinutes", ("时长", "分钟", "小时", "全天", "收盘", "null")),
    ("placeOrderShortname", ("context.counterparties", "原文", "标的")),
    ("placeOrderCloseIntent", ("动作", "持仓", "null")),
    ("placeOrderEntrustRatio", ("范围", "比例", "持仓", "不计算")),
])
def test_candidate_tool_schema_declares_field_boundaries(alias, required_semantics):
    description = _tool_order_properties()[alias]["description"]
    for semantic in required_semantics:
        assert semantic in description, (alias, semantic, description)


def test_candidate_descriptions_preserve_canonical_fields_aliases_and_types():
    canonical = SwapOrderItem.model_json_schema(by_alias=True)["properties"]
    candidate = _tool_order_properties()
    assert tuple(canonical) == ORDER_ALIASES
    assert tuple(candidate) == ORDER_ALIASES
    assert tuple(SwapPlaceOrderParams.model_fields) == ("order_list",)
    assert SwapPlaceOrderParams.model_fields["order_list"].alias == "orderList"
    assert canonical["placeOrderQuantity"]["anyOf"] == [
        {"type": "integer"}, {"type": "null"},
    ]
    assert canonical["placeOrderOrderDirection"]["anyOf"][0]["enum"] == [
        "BUY", "SELL", "SHORT_OPEN", "SHORT_CLOSE",
    ]
    assert canonical["placeOrderPriceType"]["anyOf"][0]["enum"] == [
        "LimitOrder", "MarketOrder",
    ]
    assert canonical["placeOrderAlgorithmType"]["anyOf"][0]["enum"] == [
        "POV", "TWAP", "VWAP", "ICEBERG", "SNIPER",
    ]
    for alias in ORDER_ALIASES:
        value_schema = candidate[alias]["anyOf"][0]["properties"]["value"]
        assert value_schema["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert "单位展开后的整数" not in json.dumps(candidate, ensure_ascii=False)


async def test_live_extraction_path_sends_schema_and_separate_reference_context(monkeypatch):
    captured = {}

    def structured_output(model):
        captured["tool"] = convert_to_openai_tool(model)
        return MagicMock(ainvoke=invoke)

    invoke = AsyncMock(return_value={"orderList": []})
    llm = MagicMock()
    llm.with_structured_output.side_effect = structured_output
    monkeypatch.setattr(place_order, "get_qwen_complex", lambda: llm)
    raw = "买入 LITE 273股，甲方账户，全天执行到收盘"
    counterparties = [{"shortName": "甲方账户", "ctptyId": 123}]
    result = await place_order.swap_extract_candidates({
        "raw_text": raw, "swap_counterparties": counterparties,
    })
    assert not result.get("error")
    llm.with_structured_output.assert_called_once_with(place_order.CANDIDATE_MODEL)
    messages = invoke.call_args.args[0]
    system = messages[0][1]
    assert "value 只保留本字段" in system
    assert "evidence 可以更长" in system
    assert "不因个别字段未明确而遗漏订单" in system
    assert "不推算市场开收盘时刻" in system
    payload = json.loads(messages[1][1])
    assert payload["sources"]["raw"] == raw
    assert payload["context"]["counterparties"] == counterparties
    assert "甲方账户" not in system
    description = captured["tool"]["function"]["parameters"]["properties"]["orderList"][
        "items"
    ]["properties"]["placeOrderShortname"]["description"]
    assert "context.counterparties" in description
