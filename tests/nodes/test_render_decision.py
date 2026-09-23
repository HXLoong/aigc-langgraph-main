"""render 每个分支必须在 trace 里留下 decision（ADR 0024 D3：决策树可观测）。

现役决策集合（2026-09-20 标的识别委托后端后，本地不再有 hitl_card / zero_match 卡片）：
passthrough / api_result / error:{option,swap}_backend_{missing_context,empty_result}
/ error:backend_unreachable / error:cascade_fail / unknown_intent / backend_no_result / no_reply。
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.graph.state import ErrorInfo
from app.nodes.render import render
from app.tools.receipts import SERVICE_UNAVAILABLE, UNCERTAIN_REPLY


def _decision(update: dict) -> str | None:
    entries = [e for e in update.get("trace", []) if getattr(e, "node", None) == "render"]
    assert len(entries) == 1, update.get("trace")
    return entries[0].decision


async def test_passthrough_when_subgraph_already_replied() -> None:
    out = await render({"reply_text": "已有回复"})
    assert "reply_text" not in out
    assert _decision(out) == "passthrough"


async def test_api_result_branch_passes_backend_text_through() -> None:
    out = await render({"api_result": "后端卡片", "api_code": 0, "product_type": "swap"})
    assert out["reply_text"] == "后端卡片"
    assert _decision(out) == "api_result"


async def test_api_result_branch_projects_code_500_to_service_unavailable() -> None:
    out = await render({"api_result": "内部错误堆栈", "api_code": 500, "product_type": "option"})
    assert out["reply_text"] == SERVICE_UNAVAILABLE
    assert _decision(out) == "api_result"


@pytest.mark.parametrize(
    ("product_type", "err_type", "decision"),
    [
        ("option", "MissingBackendContextError", "error:option_backend_missing_context"),
        ("option_close", "MissingBackendContextError", "error:option_backend_missing_context"),
        ("option", "EmptyBackendResultError", "error:option_backend_empty_result"),
        ("swap", "MissingBackendContextError", "error:swap_backend_missing_context"),
        ("swap", "EmptyBackendResultError", "error:swap_backend_empty_result"),
        ("swap", "BackendUnreachableError", "error:backend_unreachable"),
        ("option", "RuntimeError", "error:cascade_fail"),
    ],
)
async def test_error_branches_are_distinguished(
    product_type: str, err_type: str, decision: str
) -> None:
    out = await render({
        "product_type": product_type,
        "error": ErrorInfo(node="n", type=err_type, message="x"),
    })
    assert _decision(out) == decision
    assert out["reply_text"]


async def test_unknown_intent_uses_default_reply() -> None:
    out = await render({"product_type": "option", "intent": "unknown_intent"})
    assert out["reply_text"] == get_settings().default_reply
    assert _decision(out) == "unknown_intent"


@pytest.mark.asyncio
async def test_business_intent_without_backend_result_is_labelled() -> None:
    out = await render({"product_type": "option", "intent": "new_inquiry"})
    assert _decision(out) == "backend_no_result"


async def test_known_intent_without_receipt_is_uncertain_not_fabricated() -> None:
    out = await render({"product_type": "option", "intent": "new_inquiry",
                        "expected_action": "inquiry", "place_params": {"orderList": []}})
    assert out["reply_text"] == UNCERTAIN_REPLY
    assert _decision(out) == "backend_no_result"


async def test_no_reply_fallthrough_is_labelled() -> None:
    out = await render({"tickers": [], "place_params": {}})
    assert out["reply_text"] == get_settings().default_reply
    assert _decision(out) == "no_reply"
