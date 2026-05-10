"""M1 smoke test: 主图编译 + 端到端 stub run。

ADR 0001 D1 + ADR 0015：M1 smoke 已升级为含 intent_route 的端到端验证：
- ingest → intent_route（规则层）→ swap/option/option_close stub → persist → render
- unknown / cascade 路径走 fallback
"""
from __future__ import annotations

import pytest

from app.graph.main import build_main_graph


@pytest.mark.asyncio
async def test_main_graph_compiles() -> None:
    """ADR 0001 D6: 主图能编译。"""
    graph = build_main_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_main_graph_e2e_swap_keyword() -> None:
    """ADR 0015 第 2 层：'互换' 关键词 → product=swap → swap stub。"""
    graph = build_main_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "做一笔互换 100 手",
            "conversation_id": "smoke-1",
            "user_id": "u-smoke",
            "room_id": "r-smoke",
            "message_id": 1,
            "message_content": "做一笔互换 100 手",
        }
    )

    assert final.get("error") is None, f"unexpected error: {final.get('error')}"

    trace_nodes = [entry.node for entry in final.get("trace", [])]
    assert trace_nodes == [
        "ingest",
        "intent_route",
        "_swap_stub",
        "persist",
        "render",
    ], f"unexpected trace path: {trace_nodes}"

    assert final.get("product_type") == "swap"
    intent_route_decision = final["trace"][1].decision
    assert intent_route_decision == "rule:keyword→swap"


@pytest.mark.asyncio
async def test_main_graph_e2e_unknown_routes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0015 第 3 层 + cascade：无关键词 + LLM 判 unknown → fallback。"""
    from app.nodes import intent_route as intent_route_module

    async def fake_classify(text: str) -> str:
        return "unknown"

    monkeypatch.setattr(
        intent_route_module, "_classify_with_llm", fake_classify
    )

    graph = build_main_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "你好，在吗",
            "conversation_id": "smoke-unknown",
            "user_id": "u-smoke",
            "room_id": "r-smoke",
            "message_id": 1,
            "message_content": "你好，在吗",
        }
    )

    assert final.get("error") is None
    trace_nodes = [entry.node for entry in final.get("trace", [])]
    assert "fallback" in trace_nodes
    assert "_swap_stub" not in trace_nodes
    assert final.get("product_type") == "unknown"


@pytest.mark.asyncio
async def test_main_graph_e2e_option_close_order_no() -> None:
    """ADR 0015 第 1 层：CO- 订单号 → option_close stub。"""
    graph = build_main_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "平 CO-20260304-ABCD1234 全部",
            "conversation_id": "smoke-close",
            "user_id": "u-smoke",
            "room_id": "r-smoke",
            "message_id": 1,
            "message_content": "平 CO-20260304-ABCD1234 全部",
        }
    )

    assert final.get("error") is None
    trace_nodes = [entry.node for entry in final.get("trace", [])]
    assert "_option_close_stub" in trace_nodes
    assert final.get("product_type") == "option_close"
    assert final["trace"][1].decision == "rule:order_no→option_close"


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
