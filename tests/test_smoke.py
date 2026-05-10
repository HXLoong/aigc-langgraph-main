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
async def test_main_graph_e2e_swap_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0015 第 2 层：'互换' 关键词 → product=swap → swap 子图（intent + todo）。

    swap 子图嵌入后，trace 含子图内部节点（swap_intent / swap_todo）。
    LangGraph 0.6 子图嵌入特性：reducer add 会让 ingest/intent_route 在
    主图 + 子图 input 累积时出现两次——本测试用 contains 而非精确等于。
    """
    # mock swap.intent 的 LLM 调用（避免联网）
    from unittest.mock import AsyncMock, MagicMock

    from app.subgraphs.swap import intent as swap_intent_module
    from app.subgraphs.swap.models import SwapIntentOutput

    fake_output = SwapIntentOutput(type="place_order_request")
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        swap_intent_module, "get_qwen_structured", lambda: fake_base_llm
    )

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
    required = {
        "ingest",
        "intent_route",
        "swap_intent",
        "swap_todo",
        "persist",
        "render",
    }
    assert required.issubset(set(trace_nodes)), (
        f"missing nodes: {required - set(trace_nodes)} in {trace_nodes}"
    )

    assert final.get("product_type") == "swap"
    assert final.get("intent") == "place_order_request"
    # 验证 intent_route 决策是规则层命中
    intent_route_entries = [e for e in final["trace"] if e.node == "intent_route"]
    assert any(
        e.decision == "rule:keyword→swap" for e in intent_route_entries
    )


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
async def test_main_graph_e2e_option_close_order_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0015 第 1 层：CO- 订单号 → close 子图（intent + todo）。"""
    from unittest.mock import AsyncMock, MagicMock

    from app.subgraphs.close import intent as close_intent_module
    from app.subgraphs.close.models import CloseIntentOutput

    fake_output = CloseIntentOutput(type="close_order_request")
    fake_llm_with_schema = MagicMock()
    fake_llm_with_schema.ainvoke = AsyncMock(return_value=fake_output)
    fake_base_llm = MagicMock()
    fake_base_llm.with_structured_output = MagicMock(
        return_value=fake_llm_with_schema
    )
    monkeypatch.setattr(
        close_intent_module, "get_qwen_structured", lambda: fake_base_llm
    )

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
    required = {
        "ingest",
        "intent_route",
        "close_intent",
        "close_todo",
        "persist",
        "render",
    }
    assert required.issubset(set(trace_nodes)), (
        f"missing nodes: {required - set(trace_nodes)} in {trace_nodes}"
    )
    assert final.get("product_type") == "option_close"
    assert final.get("intent") == "close_order_request"
    intent_route_entries = [e for e in final["trace"] if e.node == "intent_route"]
    assert any(
        e.decision == "rule:order_no→option_close"
        for e in intent_route_entries
    )


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
