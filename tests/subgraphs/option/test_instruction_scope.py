"""Negation and explicit ordinals must never broaden an order operation."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import intent as intent_module
from app.subgraphs.option.models import OptionIntentOutput
from app.subgraphs.option.place_params import parse_confirm_place_params, parse_place_params

FIRST = "Q-20260918-0000000001"
SECOND = "Q-20260918-0000000002"
QUOTE = f"订单号：{FIRST}\n订单号：{SECOND}"


@pytest.mark.parametrize("raw", ["不要确认下单", "暂不确认下单", "先别确认下单"])
async def test_negated_confirmation_is_not_a_confirmation(monkeypatch, raw):
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(
        return_value=OptionIntentOutput(type="confirm_order")
    )
    monkeypatch.setattr(intent_module, "get_qwen_structured", lambda: model)
    result = await intent_module.option_intent({"raw_text": raw, "quote_content": QUOTE})
    assert result.get("intent") != "confirm_order"


@pytest.mark.parametrize("raw", ["第2笔限价10 第3笔限价20", "第1笔限价10 第1笔限价20"])
def test_invalid_ordinal_mapping_does_not_apply_to_all_orders(raw):
    with pytest.raises(ValueError, match="序号"):
        parse_place_params(raw, QUOTE)


def test_single_ordinal_selects_only_that_order():
    items = parse_place_params("第2笔限价10", QUOTE)
    assert [(item["order_id"], item["limit_price"]) for item in items] == [(SECOND, 10.0)]


def test_confirm_parameters_preserve_explicit_order_scope():
    items = parse_confirm_place_params("第2笔限价10，确认下单", QUOTE)
    assert [(item["order_id"], item["limit_price"]) for item in items] == [(SECOND, 10.0)]
