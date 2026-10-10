"""/v1/workflows/run outputs 对 expected_action 的暴露方式（ADR 0024 D2）。

state 内 expected_action 是顶层字段；wire 层为兼容既有读者（探针脚本 / 日志解析）
仍把它投影回 outputs.place_params / outputs.cancel_params，state 本身不被改写。
"""
from __future__ import annotations

from app.api.routes import _state_to_outputs


def test_expected_action_exposed_top_level_and_projected_into_envelopes() -> None:
    place = {"orderList": [{"orderId": "H-1"}]}
    state: dict = {"intent": "place_order_request", "expected_action": "place", "place_params": place}
    out = _state_to_outputs(state)  # type: ignore[arg-type]
    assert out["expected_action"] == "place"
    assert out["place_params"] == {"expected_action": "place", "orderList": [{"orderId": "H-1"}]}
    assert "expected_action" not in place, "投影不得改写 state 内的信封"


def test_cancel_envelope_gets_projection_too() -> None:
    state: dict = {"expected_action": "cancel", "cancel_params": {"orderList": [{"orderId": "Q-1"}]}}
    out = _state_to_outputs(state)  # type: ignore[arg-type]
    assert out["cancel_params"]["expected_action"] == "cancel"


def test_absent_expected_action_is_not_emitted() -> None:
    out = _state_to_outputs({"intent": "query_order", "query_filter": {"orderList": []}})  # type: ignore[arg-type]
    assert "expected_action" not in out
    assert out["query_filter"] == {"orderList": []}
