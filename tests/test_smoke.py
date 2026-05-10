"""M1 smoke test: 主图编译 + 端到端 stub run（替代 legacy tests，符合 ADR 0001 D1）."""
from __future__ import annotations

import pytest

from app.graph.main import build_main_graph


@pytest.mark.asyncio
async def test_main_graph_compiles() -> None:
    """ADR 0001 D6: 主图能编译。"""
    graph = build_main_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_main_graph_e2e_stub_run() -> None:
    """ADR 0001 #10 退出门：空状态能跑通 ingest → route → render。"""
    graph = build_main_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "M1 smoke",
            "conversation_id": "smoke-1",
            "user_id": "u-smoke",
            "room_id": "r-smoke",
            "message_id": 1,
            "message_content": "M1 smoke",
        }
    )

    assert final.get("error") is None, f"unexpected error: {final.get('error')}"

    trace_nodes = [entry.node for entry in final.get("trace", [])]
    assert trace_nodes == ["ingest", "_swap_stub", "persist", "render"], (
        f"unexpected trace path: {trace_nodes}"
    )

    # M1 默认 product_type=swap（intent_route 在 M2 才接 LLM）
    assert final.get("product_type") == "swap"
    # _swap_stub 在 M1 占位 intent
    assert final.get("intent") == "place_order_request"


@pytest.mark.asyncio
async def test_safe_node_catches_exception() -> None:
    """ADR 0001 D5: @safe_node 装饰器把异常转成 state['error']，图不崩。"""
    from typing import Any

    from app.graph.safe_node import safe_node
    from app.graph.state import AgentState

    @safe_node
    async def bad_node(state: AgentState) -> dict[str, Any]:
        raise RuntimeError("intentional fault")

    result = await bad_node({"raw_text": "x"})

    assert result.get("error") is not None
    assert result["error"].node == "bad_node"
    assert result["error"].type == "RuntimeError"
    assert "intentional fault" in result["error"].message
    assert len(result.get("trace", [])) == 1
    assert result["trace"][0].decision == "error"
