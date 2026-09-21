import pytest

from app.extraction.candidates import candidate_model
from app.subgraphs.swap.models import SwapPlaceOrderParams
from app.subgraphs.swap.normalize import normalize_candidates, normalize_field


@pytest.mark.parametrize("token,expected", [("B", "BUY"), ("L", "BUY"), ("S", "SELL")])
def test_standalone_first_direction_token(token, expected):
    assert (
        normalize_field("placeOrderOrderDirection", token, f"600519.SH {token} 100股 市价")
        == expected
    )


@pytest.mark.parametrize(
    "token,source",
    [
        ("B", "BILI.O 100股"),
        ("S", "600519.SH 100股"),
        ("B", "600519.SH 买入100股 交易对手B"),
        ("B", "600519.SH 100股 交易对手 B"),
        ("S", "600519.SH B 100股 S"),
    ],
)
def test_ticker_account_or_second_marker_cannot_be_direction(token, source):
    with pytest.raises(ValueError):
        normalize_field("placeOrderOrderDirection", token, source)


def test_candidate_short_evidence_does_not_bypass_source_scope():
    candidate = candidate_model(SwapPlaceOrderParams).model_validate(
        {
            "orderList": [
                {
                    "placeOrderOrderDirection": {"value": "B", "evidence": "B", "confidence": 0.99},
                }
            ]
        }
    )
    with pytest.raises(ValueError):
        normalize_candidates(candidate, {"raw": "600519.SH 100股 交易对手 B"})


def test_candidate_short_evidence_uses_real_direction_context():
    candidate = candidate_model(SwapPlaceOrderParams).model_validate(
        {
            "orderList": [
                {
                    "placeOrderOrderDirection": {"value": "B", "evidence": "B", "confidence": 0.99},
                }
            ]
        }
    )
    parsed, _ = normalize_candidates(candidate, {"raw": "600519.SH B 100股"})
    assert parsed.order_list[0].place_order_order_direction == "BUY"


def test_account_letter_before_direction_does_not_count_as_direction_marker():
    assert normalize_field("placeOrderOrderDirection", "S", "交易对手 B，600519.SH S 100股") == "SELL"
