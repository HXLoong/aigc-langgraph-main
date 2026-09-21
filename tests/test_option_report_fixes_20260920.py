from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from app.graph import instructions
from app.subgraphs.option import extract_inquiry
from app.subgraphs.option.place_params import parse_place_params_with_lineage

Q1, Q2 = "Q-20260920-9894130688", "Q-20260920-2309752320"
QUOTE = (
    f"序号：1\n单号：{Q1}\n期权类型：欧式看涨\n标的代码：600519.SH\n期限：1M\n行权价格：80%\n"
    f"序号：2\n单号：{Q2}\n期权类型：欧式看涨\n标的代码：600519.SH\n期限：2M\n行权价格：80%\n"
    f"订单{Q1}(序号1)：\nA. 对手甲\nB. 对手乙\n订单{Q2}(序号2)：\nA. 对手甲\nB. 对手乙"
)
RAW = "第一个单 最大跟量，200万，A，限价10\n第二个单 限价6，100万，B"


async def test_case026_batch_supplement_does_not_use_planner_llm(monkeypatch):
    model = Mock(side_effect=AssertionError("same action batch must not split"))
    monkeypatch.setattr(instructions, "get_qwen_standard", model)
    result = await instructions.plan_instructions({"raw_text": RAW, "quote_content": QUOTE})
    assert not result.get("error"), result
    assert result["sub_instructions"] == []
    model.assert_not_called()


def test_case026_each_order_keeps_its_own_quote_fields():
    result = parse_place_params_with_lineage(RAW, QUOTE)
    assert [o["order_id"] for o in result.orders] == [Q1, Q2]
    assert [o["tenor"] for o in result.orders] == ["1M", "2M"]
    assert [o["notional_amount"] for o in result.orders] == ["2000000", "1000000"]
    assert [o["short_name"] for o in result.orders] == ["对手甲", "对手乙"]
    assert [o["limit_price"] for o in result.orders] == [10, 6]
    assert result.fields[1]["tenor"].value == "2M"
    assert Q1 not in result.fields[1]["tenor"].evidence


def test_batch_field_evidence_is_an_original_contiguous_fragment():
    result = parse_place_params_with_lineage(RAW, QUOTE)
    for fields in result.fields:
        for record in fields.values():
            if record.origin == "quote":
                assert record.evidence in QUOTE


def test_pov_update_does_not_overwrite_strike():
    result = parse_place_params_with_lineage("改成POV12%", f"单号：{Q1}\n行权价格：80%")
    assert result.orders[0]["pov_ratio"] == 12
    assert result.orders[0]["strike_percentage"] == 80


@pytest.mark.parametrize("token", ["call", "CALL", "Call", "看涨"])
async def test_case027_raw_alias_survives_extraction_then_normalizes(monkeypatch, token):
    raw = f"宁德时代，100{token}，1M"

    def candidate(value):
        return {"value": value, "evidence": value, "confidence": 0.99}

    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value={
            "orderList": [
                {
                    "stockCode": candidate("宁德时代"),
                    "optionType": candidate(token),
                    "strikePercentage": candidate("100"),
                    "tenor": candidate("1M"),
                }
            ]
        }
    )
    monkeypatch.setattr(extract_inquiry, "get_qwen_thinking", lambda: model)
    extracted = await extract_inquiry.inquiry_extract({"raw_text": raw})
    assert not extracted.get("error"), extracted
    normalized = await extract_inquiry.inquiry_normalize(extracted)
    assert normalized["iq_order_list"][0]["optionType"] == "欧式看涨"
    assert normalized["iq_order_list"][0]["strikePercentage"] == 100
    record = normalized["field_records"]["option/inquiry.orderList.0.optionType"]
    assert record.value == "欧式看涨" and record.evidence == token


async def test_planner_uses_text_evidence_and_code_computes_offsets(monkeypatch):
    raw = "买甲；然后卖乙"
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value={
            "instructions": [
                {"text": "买甲", "evidence": "买甲", "confidence": 0.99},
                {"text": "卖乙", "evidence": "卖乙", "confidence": 0.99, "depends_on": [0]},
            ]
        }
    )
    monkeypatch.setattr(instructions, "get_qwen_standard", lambda: model)
    result = await instructions.plan_instructions({"raw_text": raw})
    assert not result.get("error"), result
    assert [(i["start"], i["end"]) for i in result["sub_instructions"]] == [(0, 2), (5, 7)]
    schema = model.with_structured_output.call_args.args[0].model_json_schema()
    assert all("start" not in d.get("properties", {}) for d in schema.get("$defs", {}).values())


@pytest.mark.parametrize(
    "suffix", ["先不下单", "如果成交后再查询", "再平仓", "操作H-20260920-1234567890"]
)
def test_batch_shortcut_does_not_discard_unknown_or_negated_instructions(suffix):
    from app.subgraphs.option.place_params import is_quoted_batch_supplement

    assert not is_quoted_batch_supplement(RAW + "，" + suffix, QUOTE)
