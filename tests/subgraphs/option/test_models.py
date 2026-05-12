"""OptionIntentOutput Pydantic 模型测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.subgraphs.option.models import OptionIntentOutput


# ============================================================
# 10 个合法 type 值（ADR 0011 二次修订，不含 close_order_*）
# ============================================================


@pytest.mark.parametrize(
    "intent_type",
    [
        "new_inquiry",
        "place_order_from_quote",
        "request_modify_order",
        "request_cancel_order",
        "cancel_order_request",
        "confirm_order",
        "confirm_cancel_order",
        "confirm_modify_order",
        "query_order_status",
        "unknown_intent",
    ],
)
def test_all_ten_intent_types_accepted(intent_type: str) -> None:
    obj = OptionIntentOutput(type=intent_type)  # type: ignore[arg-type]
    assert obj.type == intent_type


@pytest.mark.parametrize(
    "close_intent",
    [
        "close_order_query",
        "close_order_request",
        "close_order_confirm",
        "close_order_cancel_request",
        "close_order_cancel_confirm",
        "close_order_order_query",
    ],
)
def test_close_intents_rejected_by_option_schema(close_intent: str) -> None:
    """ADR 0011 二次修订：close_order_* 归 close 子图，option schema 必须拒绝。"""
    with pytest.raises(ValidationError):
        OptionIntentOutput(type=close_intent)  # type: ignore[arg-type]


def test_invalid_intent_type_rejected() -> None:
    with pytest.raises(ValidationError):
        OptionIntentOutput(type="not_a_real_intent")  # type: ignore[arg-type]


def test_extra_fields_ignored() -> None:
    params = OptionIntentOutput.model_validate(
        {"type": "new_inquiry", "extra_garbage": "x"}
    )
    assert params.type == "new_inquiry"


def test_missing_type_field_raises() -> None:
    with pytest.raises(ValidationError):
        OptionIntentOutput.model_validate({})
