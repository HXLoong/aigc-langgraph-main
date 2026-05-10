"""fallback 节点测试。"""
from __future__ import annotations

import pytest

from app.graph.state import ErrorInfo
from app.nodes.fallback import fallback


@pytest.mark.asyncio
async def test_fallback_records_origin_node() -> None:
    state = {
        "error": ErrorInfo(
            node="swap.intent", type="ValidationError", message="bad LLM output"
        )
    }
    result = await fallback(state)
    assert "trace" in result
    trace = result["trace"]
    assert len(trace) == 1
    entry = trace[0]
    assert entry.node == "fallback"
    assert "swap.intent" in (entry.decision or "")


@pytest.mark.asyncio
async def test_fallback_when_no_error_in_state() -> None:
    """fallback 节点被错误调用（state 没 error）时仍不应崩。"""
    result = await fallback({})
    assert "trace" in result
    assert len(result["trace"]) == 1
    decision = result["trace"][0].decision or ""
    assert "no_error" in decision
