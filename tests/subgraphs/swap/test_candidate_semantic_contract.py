"""Regression contracts for the model request, before deterministic field validation."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.subgraphs.swap import place_order


@pytest.mark.parametrize("alias,required", [
    ("placeOrderQuantity", ("正负号", "不取绝对值", "不展开")),
    ("placeOrderOrderDirection", ("本轮", "连续", "持仓范围", "quote/history", "null")),
    ("placeOrderCloseIntent", (
        "本轮", "连续", "卖出动作与持仓范围", "仅含范围", "quote/history", "null",
    )),
    ("placeOrderEntrustRatio", ("同一连续", "本笔动作", "持仓状态", "不计算")),
    ("placeOrderAlgorithmType", ("同时出现", "算法名", "风格", "不遗漏", "不附带")),
    ("placeOrderPovPercent", ("比例片段", "算法名", "百分号")),
])
async def test_request_tool_schema_enforces_current_order_semantics(monkeypatch, alias, required):
    captured = {}
    invoke = AsyncMock(return_value={"orderList": []})

    def structured_output(model):
        captured["tool"] = convert_to_openai_tool(model)
        return MagicMock(ainvoke=invoke)

    llm = MagicMock()
    llm.with_structured_output.side_effect = structured_output
    monkeypatch.setattr(place_order, "get_qwen_complex", lambda: llm)
    result = await place_order.swap_extract_candidates({"raw_text": "甲证券，剩余持仓"})
    assert not result.get("error")
    llm.with_structured_output.assert_called_once_with(place_order.CANDIDATE_MODEL)
    invoke.assert_awaited_once()
    properties = captured["tool"]["function"]["parameters"]["properties"]["orderList"][
        "items"
    ]["properties"]
    for semantic in required:
        assert semantic in properties[alias]["description"], (alias, semantic)


async def test_request_preserves_signed_quantity_and_separates_old_actions(monkeypatch):
    raw = "甲证券，剩余持仓 -120股，VWAP全天"
    candidate = {"value": "-120股", "evidence": "剩余持仓 -120股", "confidence": 1.0}
    invoke = AsyncMock(return_value={"orderList": [{"placeOrderQuantity": candidate}]})
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr(place_order, "get_qwen_complex", lambda: llm)
    result = await place_order.swap_extract_candidates({
        "raw_text": raw,
        "quote_content": "上一笔卖出平仓",
        "history_messages": [{"id": "old", "role": "user", "content": "买入甲证券"}],
    })
    assert not result.get("error")
    order = result["sp_candidates"]["orderList"][0]
    assert order["placeOrderQuantity"]["value"] == "-120股"
    assert order["placeOrderOrderDirection"] is None
    assert order["placeOrderCloseIntent"] is None
    messages = invoke.call_args.args[0]
    system = messages[0][1]
    assert "不从 quote/history 复制本轮动作" in system
    assert "本笔动作与持仓范围的关系" in system
    assert "同一连续原文证据" in system
    assert "负数不取绝对值" in system
    assert "不推算市场开收盘时刻" in system
    sources = json.loads(messages[1][1])["sources"]
    assert sources["raw"] == raw
    assert sources["quote"] == "上一笔卖出平仓"
    assert sources["history:old"] == "买入甲证券"
