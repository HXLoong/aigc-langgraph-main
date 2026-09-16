"""option.extract_confirm_cancel 节点测试（确认撤单，确定性提取，无 LLM）。

原提示词规约：从 quote_content（机器人撤单确认消息）提取全部 Q- 订单号；
多单场景全部保留；quote 无订单号 → orderId: null。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.subgraphs.option import extract_confirm_cancel as ecc_module
from app.subgraphs.option.extract_confirm_cancel import option_extract_confirm_cancel


def _patch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    backend = AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"})
    monkeypatch.setattr(ecc_module, "call_option_backend", backend)

    def _forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("去 LLM 化节点不应调用 LLM")

    monkeypatch.setattr(ecc_module, "get_qwen_thinking", _forbid, raising=False)
    return backend


@pytest.mark.parametrize(
    ("raw_text", "quote_content", "expected_ids"),
    [
        ("确认撤单", "请确认撤单 Q-20250903-000027", ["Q-20250903-000027"]),
        (
            "确认撤单",
            "待撤订单：Q-20250903-000027、Q-20250903-000031",
            ["Q-20250903-000027", "Q-20250903-000031"],
        ),
        ("确认撤单 Q-20250903-000099", "无订单号的卡片", [None]),
        ("确认撤单", None, [None]),
    ],
    ids=["single", "multi", "raw-only-not-extracted", "no-quote"],
)
@pytest.mark.asyncio
async def test_confirm_cancel_extracts_from_quote_only(
    monkeypatch: pytest.MonkeyPatch,
    raw_text: str,
    quote_content: str | None,
    expected_ids: list[str | None],
) -> None:
    backend = _patch(monkeypatch)
    result = await option_extract_confirm_cancel(
        {
            "raw_text": raw_text,
            "quote_content": quote_content,
            "intent": "confirm_cancel_order",
        }
    )
    assert result["confirm"]["action"] == "cancel"
    order_list = result["confirm"]["orderList"]
    assert [item["orderId"] for item in order_list] == expected_ids
    assert backend.await_args.kwargs["order_list"] == order_list


@pytest.mark.asyncio
async def test_writes_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch)
    result = await option_extract_confirm_cancel(
        {
            "raw_text": "确认撤单",
            "quote_content": "请确认撤单 Q-20250903-000027",
            "intent": "confirm_cancel_order",
        }
    )
    trace = result.get("trace", [])
    assert len(trace) == 1
    assert trace[0].node == "option_extract_confirm_cancel"
    assert "deterministic" in trace[0].decision
    assert "action=cancel" in trace[0].decision
