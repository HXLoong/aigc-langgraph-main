"""CloseIntentOutput Pydantic 模型测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.subgraphs.close.models import CloseIntentOutput


@pytest.mark.parametrize(
    "intent_type",
    [
        "close_order_query",
        "close_order_order_query",
        "close_order_request",
        "close_order_confirm",
        "close_order_cancel_request",
        "close_order_cancel_confirm",
        "unknown_intent",
    ],
)
def test_all_seven_intent_types_accepted(intent_type: str) -> None:
    obj = CloseIntentOutput(type=intent_type)  # type: ignore[arg-type]
    assert obj.type == intent_type


@pytest.mark.parametrize(
    "non_close_intent",
    [
        "place_order_request",
        "new_inquiry",
        "request_modify_order",
    ],
)
def test_non_close_intents_rejected(non_close_intent: str) -> None:
    """ADR 0011 二次修订：close 子图只处理 close_order_* + unknown_intent。"""
    with pytest.raises(ValidationError):
        CloseIntentOutput(type=non_close_intent)  # type: ignore[arg-type]


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        CloseIntentOutput.model_validate(
            {"type": "close_order_query", "extra": "x"}
        )


def test_missing_type_raises() -> None:
    with pytest.raises(ValidationError):
        CloseIntentOutput.model_validate({})
