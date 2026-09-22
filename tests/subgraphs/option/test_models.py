"""OptionIntentOutput Pydantic 模型测试（7 基础意图 + unknown_intent）。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.subgraphs.option.models import OptionIntentOutput

# ============================================================
# 8 个合法 type 值（7 基础意图 + unknown_intent，不含 close_order_*，
# 不再含 request_modify_order / confirm_modify_order）
# ============================================================


@pytest.mark.parametrize(
    "intent_type",
    [
        "new_inquiry",
        "place_order_from_quote",
        "confirm_order",
        "cancel_order_request",
        "request_cancel_order",
        "confirm_cancel_order",
        "query_order_status",
        "unknown_intent",
    ],
)
def test_all_eight_intent_types_accepted(intent_type: str) -> None:
    obj = OptionIntentOutput(type=intent_type, confidence=0.91, evidence=[{"text": "本轮意图模型测试输入", "origin": "raw"}])  # type: ignore[arg-type]
    assert obj.type == intent_type


@pytest.mark.parametrize(
    "removed_intent",
    ["request_modify_order", "confirm_modify_order"],
)
def test_removed_modify_intents_rejected(removed_intent: str) -> None:
    """期权无独立改单流程（DSL v2 迁移收窄），这两个旧枚举值必须被拒绝。"""
    with pytest.raises(ValidationError):
        OptionIntentOutput(type=removed_intent, confidence=0.91, evidence=[{"text": "本轮意图模型测试输入", "origin": "raw"}])  # type: ignore[arg-type]


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
        OptionIntentOutput(type=close_intent, confidence=0.91, evidence=[{"text": "本轮意图模型测试输入", "origin": "raw"}])  # type: ignore[arg-type]


def test_invalid_intent_type_rejected() -> None:
    with pytest.raises(ValidationError):
        OptionIntentOutput(type="not_a_real_intent", confidence=0.91, evidence=[{"text": "本轮意图模型测试输入", "origin": "raw"}])  # type: ignore[arg-type]


def test_extra_fields_ignored() -> None:
    params = OptionIntentOutput.model_validate(
        {"type": "new_inquiry", "confidence": .91, "evidence": [{"text": "查询", "origin": "raw"}], "extra_garbage": "x"}
    )
    assert params.type == "new_inquiry"


def test_missing_type_field_raises() -> None:
    with pytest.raises(ValidationError):
        OptionIntentOutput.model_validate({})
