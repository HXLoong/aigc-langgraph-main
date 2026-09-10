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
    """ADR 0015 第 2 层：'互换' 关键词 → swap 子图 → place_order_request →
    swap_place_order + swap_place_order_submit 真节点链。"""
    from unittest.mock import AsyncMock, MagicMock

    from app.subgraphs.swap import intent as swap_intent_module
    from app.subgraphs.swap import place_order as swap_po_module
    from app.subgraphs.swap.models import (
        SwapIntentOutput,
        SwapOrderItem,
        SwapPlaceOrderParams,
    )
    from app.subgraphs.ticker.resolver import TickerResolution
    from app.tools.models import CommonResult

    def _patch(module: object, value: object, fn: str = "get_qwen_thinking") -> None:
        fake_llm = MagicMock()
        fake_llm.ainvoke = AsyncMock(return_value=value)
        fake_base = MagicMock()
        fake_base.with_structured_output = MagicMock(return_value=fake_llm)
        monkeypatch.setattr(module, fn, lambda: fake_base)

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        return CommonResult(code=0, msg="ok", data={"orderId": "H-20260828-0000000001"})

    monkeypatch.setattr(
        "app.tools.swap_client.SwapClientHttpx.operate", _fake_operate
    )

    _patch(swap_intent_module, SwapIntentOutput(type="place_order_request"))
    _patch(
        swap_po_module,
        SwapPlaceOrderParams(
            orderList=[
                SwapOrderItem(
                    placeOrderQuantity=100,
                    placeOrderOrderDirection="BUY",
                )
            ]
        ),
        fn="get_qwen_complex",
    )
    monkeypatch.setattr(
        swap_po_module,
        "resolve_ticker_full",
        AsyncMock(return_value=TickerResolution(resolved=[], hitl_pending=[])),
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
            "history_messages": [
                {"role": "user", "content": "上一轮消息"},
            ],
        }
    )

    assert final.get("error") is None, f"unexpected error: {final.get('error')}"

    trace_nodes = [entry.node for entry in final.get("trace", [])]
    required = {
        "ingest",
        "intent_route",
        "swap_intent",
        "swap_place_order",
        "persist",
        "render",
    }
    assert required.issubset(set(trace_nodes)), (
        f"missing nodes: {required - set(trace_nodes)} in {trace_nodes}"
    )
    assert trace_nodes.count("ingest") == 1
    assert trace_nodes.count("pre_route") == 1
    assert trace_nodes.count("intent_route") == 1
    from app.graph.state import Message

    history = [Message.model_validate(message) for message in final["history_messages"]]
    assert [(message.role, message.content) for message in history] == [
        ("user", "上一轮消息"),
        ("user", "做一笔互换 100 手"),
        ("assistant", final["reply_text"]),
    ]

    assert final.get("product_type") == "swap"
    assert final.get("intent") == "place_order_request"
    intent_route_entries = [e for e in final["trace"] if e.node == "intent_route"]
    # DSL v2 路由：decision 格式为 "rule→<DSL 标签>"（规则层标签见 route_rules.py）
    assert any(
        e.decision == "rule→互换-文本" for e in intent_route_entries
    )
    # 验证 swap.place_order 真节点写入了 place_params
    assert final.get("place_params", {}).get("expected_action") == "place"


@pytest.mark.asyncio
async def test_main_graph_e2e_unknown_routes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0015 第 3 层 + cascade：无关键词 + LLM 判 unknown → fallback。"""
    from app.nodes import intent_route as intent_route_module

    async def fake_classify(text: str, quote_content: str | None = None) -> str:
        return "unknown"

    monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake_classify)

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
async def test_main_graph_trace_is_isolated_per_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一会话的下一轮只返回当轮 trace，不重复携带上一轮节点。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.nodes import intent_route as intent_route_module

    async def fake_classify(text: str, quote_content: str | None = None) -> str:
        return "unknown"

    monkeypatch.setattr(intent_route_module, "_classify_with_llm", fake_classify)

    graph = build_main_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "trace-turns"}}
    base = {
        "conversation_id": "trace-turns",
        "user_id": "u-smoke",
        "room_id": "r-smoke",
    }
    first = await graph.ainvoke(
        {**base, "raw_text": "第一轮", "message_id": 1, "message_content": "第一轮"},
        config=config,
    )
    second = await graph.ainvoke(
        {**base, "raw_text": "第二轮", "message_id": 2, "message_content": "第二轮"},
        config=config,
    )

    expected = [
        "ingest", "pre_route", "intent_route", "fallback", "persist_intent", "persist", "render",
    ]
    assert [entry.node for entry in first["trace"]] == expected
    assert [entry.node for entry in second["trace"]] == expected
    assert first["trace"][4].decision == "skipped"
    assert second["trace"][4].decision == "skipped"
    assert [(message.role, message.content) for message in second["history_messages"]] == [
        ("user", "第一轮"), ("assistant", first["reply_text"]),
        ("user", "第二轮"), ("assistant", second["reply_text"]),
    ]


@pytest.mark.asyncio
async def test_main_graph_e2e_option_close_order_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0015 第 1 层：CO- 订单号 → close 子图 → close_order_request → place_close 真节点。"""
    from unittest.mock import AsyncMock, MagicMock

    from app.subgraphs.close import intent as close_intent_module
    from app.subgraphs.close import place_close as close_pc_module
    from app.subgraphs.close.models import (
        CloseIntentOutput,
        CloseOrderItem,
        ClosePlaceParams,
    )
    from app.tools.models import CommonResult

    def _patch(module: object, value: object, fn: str = "get_qwen_thinking") -> None:
        fake_llm = MagicMock()
        fake_llm.ainvoke = AsyncMock(return_value=value)
        fake_base = MagicMock()
        fake_base.with_structured_output = MagicMock(return_value=fake_llm)
        monkeypatch.setattr(module, fn, lambda: fake_base)

    async def _fake_query_close_orders(self, order_ids=None, contract_codes=None):  # type: ignore[no-untyped-def]
        return CommonResult(code=0, msg="ok", data=[])

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        return CommonResult(code=0, msg="ok", data="mock-backend-result")

    monkeypatch.setattr(
        "app.tools.option_client.OptionClientHttpx.query_close_orders",
        _fake_query_close_orders,
    )
    monkeypatch.setattr(
        "app.tools.option_client.OptionClientHttpx.operate", _fake_operate
    )

    _patch(close_intent_module, CloseIntentOutput(type="close_order_request"))
    _patch(
        close_pc_module,
        ClosePlaceParams(
            closeOrderList=[
                CloseOrderItem(
                    orderId="CO-20260304-ABCD1234",
                    confirmFullClose=True,
                )
            ]
        ),
        fn="get_qwen_thinking",
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
        "close_place_close",
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
        e.decision == "rule→期权平仓-文本" for e in intent_route_entries
    )
    # 验证 close.place_close 输出确实写入 state['close_params']
    close_params = final.get("close_params", {})
    assert close_params.get("closeOrderList")
    assert close_params["closeOrderList"][0]["orderId"] == "CO-20260304-ABCD1234"


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
