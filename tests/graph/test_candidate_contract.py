"""Canonical field definitions generate raw evidence schemas, without duplicate field tables."""
import importlib

import pytest
from pydantic import BaseModel, Field, ValidationError


class Item(BaseModel):
    amount: str | None = Field(default=None, alias="notionalAmount", description="名义本金原文")


class Orders(BaseModel):
    orders: list[Item] = Field(alias="orderList", description="订单列表")


def api():
    return importlib.import_module("app.extraction.candidates")


def test_evidence_model_preserves_aliases_and_unpacks_only_verified_values():
    module = api()
    raw_type = module.candidate_model(Orders)
    raw = raw_type.model_validate({"orderList": [{"notionalAmount": {
        "value": "100万", "evidence": "100万", "confidence": .8,
    }}]})
    canonical, records = module.unpack_candidates(Orders, raw, {"raw": "下单100万"}, scope="option/main")
    assert canonical.orders[0].amount == "100万"
    record = records["option/main.orderList.0.notionalAmount"]
    assert record.source == "user" and record.evidence == "100万" and record.confidence == .8


def test_direct_final_value_is_not_accepted_as_an_evidence_claim():
    with pytest.raises(ValidationError):
        api().candidate_model(Orders).model_validate({"orderList": [{"notionalAmount": "1000000"}]})


def test_untrusted_candidate_never_reaches_canonical_model():
    module = api()
    raw = module.candidate_model(Orders).model_validate({"orderList": [{"notionalAmount": {
        "value": "200万", "evidence": "200万", "confidence": 1,
    }}]})
    with pytest.raises(ValueError, match="evidence"):
        module.unpack_candidates(Orders, raw, {"raw": "下单100万"}, scope="option/main")


def test_source_context_has_stable_history_references():
    from app.graph.state import Message

    message = Message(role="user", content="100万")
    sources = api().evidence_sources({"raw_text": "确认", "quote_content": "原订单", "history_messages": [message]})
    assert sources["raw"] == "确认" and sources["quote"] == "原订单"
    assert sources[f"history:{message.id}"] == "100万"
