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
    ("market_selection", ("港股", "深港通", "不推断")),
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
    assert tuple(candidate) == tuple("market_selection" if key == "placeOrderTransactionType" else key
                                     for key in ORDER_ALIASES)
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
        input_alias = "market_selection" if alias == "placeOrderTransactionType" else alias
        value_schema = candidate[input_alias]["anyOf"][0]["properties"]["value"]
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


def test_model_market_selection_name_serializes_to_unchanged_java_field():
    from app.subgraphs.swap.normalize import normalize_candidates

    properties = _tool_order_properties()
    assert 'market_selection' in properties
    assert 'placeOrderTransactionType' not in properties
    cell = {'value': '港股', 'evidence': '港股', 'confidence': .95}
    candidate = place_order.CANDIDATE_MODEL.model_validate({'orderList': [{'market_selection': cell}]})
    dumped = candidate.model_dump(by_alias=True)
    assert dumped['orderList'][0]['placeOrderTransactionType']['value'] == '港股'
    assert 'market_selection' not in dumped['orderList'][0]
    # 节点保存/恢复仍使用既有候选及 Java wire 名称。
    restored = place_order.CANDIDATE_MODEL.model_validate(dumped)
    params, records = normalize_candidates(restored, {'raw': '港股'})
    assert params.model_dump()['orderList'][0]['placeOrderTransactionType'] == 'HK_STOCK'
    assert 'swap/place_order.orderList.0.placeOrderTransactionType' in records


def test_conflicting_model_and_wire_input_aliases_are_not_silently_selected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match='conflicting extraction aliases'):
        place_order.CANDIDATE_MODEL.model_validate({'orderList': [{
            'market_selection': {'value': '港股', 'evidence': '港股', 'confidence': .95},
            'placeOrderTransactionType': {'value': '美股', 'evidence': '美股', 'confidence': .95},
        }]})
