"""字段改名必须保留 Java JSON、结构化输出 schema 和旧 checkpoint 契约。"""
import json

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import Field, create_model

from app.graph.business_params import validated_place_params
from app.graph.state import TickerCandidate
from app.tools.option_client import GoatsOptionRfqReqVO


@pytest.mark.parametrize("with_sources", [False, True])
def test_legacy_ticker_checkpoint_roundtrip(with_sources: bool) -> None:
    fields = {"windCode": (str, ...), "from_goats": (bool, True)}
    if with_sources:
        fields["sourceKeywords"] = (list[str], Field(default_factory=list))
    legacy_model = create_model("TickerCandidate", __module__="app.graph.state", **fields)
    payload = {"windCode": "600519.SH", "from_goats": True}
    if with_sources:
        payload["sourceKeywords"] = ["茅台", "600519"]
    serde = JsonPlusSerializer(allowed_msgpack_modules=[("app.graph.state", "TickerCandidate")])
    restored = serde.loads_typed(serde.dumps_typed(legacy_model(**payload)))
    assert isinstance(restored, TickerCandidate)
    assert restored.wind_code == "600519.SH"
    assert restored.source_keywords == payload.get("sourceKeywords", [])
    assert restored.from_goats is True
    expected = {**payload, "sourceKeywords": payload.get("sourceKeywords", [])}
    assert restored.model_dump(exclude_none=True) == {**expected, "transactionTypeLists": []}
    assert serde.loads_typed(serde.dumps_typed(restored)) == restored
    assert json.loads(restored.model_dump_json()) == restored.model_dump(mode="json")
    assert "sourceKeywords" in TickerCandidate.model_json_schema()["properties"]


@pytest.mark.parametrize("key", ["participateRate", "participate_rate"])
def test_rfq_alias_preserves_numeric_normalization_and_json(key: str) -> None:
    rfq = GoatsOptionRfqReqVO.model_validate({key: [0.8, 1], "chatInstrument": "600519.SH"})
    assert rfq.participate_rate == ["0.8", "1"]
    assert rfq.model_dump(exclude_none=True) == {
        "chatInstrument": "600519.SH", "participateRate": ["0.8", "1"],
    }
    assert "participateRate" in rfq.model_json_schema()["properties"]


def test_state_envelope_preserves_only_explicit_alias_keys() -> None:
    assert validated_place_params(orderList=[]) == {"orderList": []}
    assert validated_place_params(expected_action="place") == {"expected_action": "place"}
    assert validated_place_params(order_list=[{"orderId": "Q-1"}]) == {
        "orderList": [{"orderId": "Q-1"}],
    }
