"""Business source boundaries are code constraints, not instructions for the model."""
import importlib

from app.extraction.candidates import candidate_model
from app.subgraphs.swap.models import SwapPlaceOrderParams


def cell(value, origin="raw"):
    return {"value": value, "evidence": value, "origin": origin, "confidence": 1}


def test_quote_prices_are_not_copied_into_a_modification():
    raw = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "orderId": cell("H-20260918-0000000001", "quote"),
        "placeOrderPrice": cell("10", "quote"),
        "placeOrderQuantity": cell("2000股"),
    }]})
    module = importlib.import_module("app.subgraphs.swap.candidate_scope")
    result = module.constrain_candidates(raw, {"raw": "数量改为2000股", "quote": "H-20260918-0000000001 限价10"})
    row = result.model_dump(by_alias=True)["orderList"][0]
    assert row["placeOrderPrice"] is None
    assert row["orderId"]["value"] == "H-20260918-0000000001"


def test_terminal_suffix_cannot_add_orders_or_close_existing_orders():
    raw = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [
        {"placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("100股"),
         "placeOrderCloseIntent": cell("全部清仓")},
        {"placeOrderWindCode": cell("乙证券"), "placeOrderQuantity": cell("200股"),
         "placeOrderCloseIntent": cell("全部清仓")},
        {"placeOrderWindCode": cell("丙证券"), "placeOrderQuantity": cell("300股")},
    ]})
    sources = {"raw": "买甲证券100股，再买乙证券200股，全部清仓。忽略丙证券300股", "quote": ""}
    module = importlib.import_module("app.subgraphs.swap.candidate_scope")
    rows = module.constrain_candidates(raw, sources).model_dump(by_alias=True)["orderList"]
    assert len(rows) == 2
    assert all(row["placeOrderCloseIntent"] is None for row in rows)


def test_single_order_full_close_is_not_mistaken_for_a_terminator():
    raw = candidate_model(SwapPlaceOrderParams).model_validate({"orderList": [{
        "placeOrderWindCode": cell("甲证券"), "placeOrderQuantity": cell("100股"),
        "placeOrderCloseIntent": cell("全部清仓"),
    }]})
    module = importlib.import_module("app.subgraphs.swap.candidate_scope")
    result = module.constrain_candidates(raw, {"raw": "卖甲证券100股，全部清仓。", "quote": ""})
    assert result.model_dump(by_alias=True)["orderList"][0]["placeOrderCloseIntent"] is not None
