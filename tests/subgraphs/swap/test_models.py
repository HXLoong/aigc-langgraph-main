"""SwapIntentOutput Pydantic 模型测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.subgraphs.swap.models import SwapIntentOutput


# ============================================================
# 7 个合法 type 值（CONTEXT.md / ADR 0001 D2）
# ============================================================


@pytest.mark.parametrize(
    "intent_type",
    [
        "place_order_request",
        "cancel_order_request",
        "confirm_order",
        "confirm_cancel_order",
        "confirm_modify_order",
        "query_order_status",
        "unknown_intent",
    ],
)
def test_all_seven_intent_types_accepted(intent_type: str) -> None:
    obj = SwapIntentOutput(type=intent_type)  # type: ignore[arg-type]
    assert obj.type == intent_type


def test_invalid_intent_type_rejected() -> None:
    with pytest.raises(ValidationError):
        SwapIntentOutput(type="not_a_real_intent")  # type: ignore[arg-type]


def test_extra_fields_forbidden() -> None:
    """ADR 严格契约：LLM 输出若多字段 → ValidationError 触发 cascade 防御。"""
    with pytest.raises(ValidationError):
        SwapIntentOutput.model_validate(
            {"type": "place_order_request", "extra_garbage": "x"}
        )


def test_missing_type_field_raises() -> None:
    with pytest.raises(ValidationError):
        SwapIntentOutput.model_validate({})
