"""Swap extraction separates raw evidence, deterministic values and GOATS resolution."""
from unittest.mock import AsyncMock, MagicMock

from app.extraction.candidates import candidate_model
from app.graph.state import TickerCandidate
from app.subgraphs.swap import place_order as place
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.ticker.resolver import TickerResolution


async def test_swap_raw_quantity_is_normalized_and_records_keep_evidence(monkeypatch):
    def field(value):
        return {"value": value, "evidence": value, "confidence": .9, "origin": "raw"}
    raw = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderWindCode": field("甲证券"), "placeOrderQuantity": field("1.5万股"),
        "placeOrderOrderDirection": field("买入"), "placeOrderPriceType": field("市价"),
    }]})
    model = MagicMock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value=raw)
    monkeypatch.setattr(place, "get_qwen_complex", lambda: model)
    monkeypatch.setattr(place, "resolve_ticker_full", AsyncMock(return_value=TickerResolution(
        resolved=[TickerCandidate(windCode="600000.SH", insShtDesc="甲证券", from_goats=True)],
        hitl_pending=[],
    )))
    result = await place.swap_place_order({"raw_text": "甲证券买入1.5万股，市价"})
    assert not result.get("error")
    order = result["place_params"]["orderList"][0]
    assert order["placeOrderQuantity"] == 15000 and order["placeOrderQuantityUnit"] == "SHARE"
    assert order["placeOrderOrderDirection"] == "BUY" and order["placeOrderWindCode"] == "600000.SH"
    record = result["field_records"]["swap/place_order.orderList.0.placeOrderQuantity"]
    assert record.value == 15000 and record.evidence == "1.5万股" and record.locked
    assert "swap_normalize" in [entry.node for entry in result["trace"]]


def test_swap_place_is_a_native_stage_graph():
    graph = place.build_place_graph()
    assert {"swap_extract_candidates", "swap_normalize", "swap_resolve", "swap_place_result"} <= set(graph.builder.nodes)
