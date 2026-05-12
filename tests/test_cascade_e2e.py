"""cascade 防御端到端集成测试（CLAUDE.md 核心原则第 8 条）。

层级覆盖：
1. 主图层：intent_route 抛错 → state['error'] 写入 → _route_after_intent 跳 fallback
2. 子图层：每个子图（swap / option / close）的 intent 节点抛错 → 跳 *_unknown
3. 端到端：异常不让图崩，trace 完整记录失败节点

验证机制：
- @safe_node 捕获异常 → 写 state['error']: ErrorInfo
- conditional 路由先 has_error(state) → 短路到 fallback / *_unknown
- render 节点必须仍执行（友好回复给 API 层）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph.main import build_main_graph
from app.subgraphs.close import build_close_graph
from app.subgraphs.close import intent as close_intent_module
from app.subgraphs.option import build_option_graph
from app.subgraphs.option import intent as option_intent_module
from app.subgraphs.swap import build_swap_graph
from app.subgraphs.swap import intent as swap_intent_module


# ============================================================
# Helpers
# ============================================================


def _patch_llm_to_raise(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    exc: Exception,
    factory_name: str = "get_qwen_thinking",
) -> None:
    """让目标模块里的 LLM 调用抛指定异常。

    覆盖 with_structured_output().ainvoke() 抛错的场景（最贴近真实 LLM 失败）。
    """
    fake_structured = MagicMock()
    fake_structured.ainvoke = AsyncMock(side_effect=exc)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_structured)
    monkeypatch.setattr(module, factory_name, lambda: fake_base)


def _base_state(raw: str = "互换 测试") -> dict[str, object]:
    return {
        "raw_text": raw,
        "conversation_id": "cascade-e2e",
        "user_id": "u",
        "room_id": "r",
        "message_id": 1,
        "message_content": raw,
    }


def _trace_nodes(final: dict) -> list[str]:
    return [e.node for e in final.get("trace", [])]


# ============================================================
# 子图层：swap.intent 抛错 → swap_unknown
# ============================================================


@pytest.mark.asyncio
async def test_swap_intent_error_routes_to_swap_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """swap.intent LLM 异常 → @safe_node 写 error → 路由到 swap_unknown。"""
    _patch_llm_to_raise(
        monkeypatch, swap_intent_module, ValueError("LLM blew up")
    )

    graph = build_swap_graph()
    final = await graph.ainvoke({**_base_state("互换下单"), "intent": None})

    nodes = _trace_nodes(final)
    assert "swap_intent" in nodes, nodes
    assert "swap_unknown" in nodes, nodes
    assert "swap_place_order" not in nodes
    assert "swap_confirm" not in nodes

    err = final.get("error")
    assert err is not None
    assert err.node == "swap_intent"
    assert err.type == "ValueError"


# ============================================================
# 子图层：option.intent 抛错 → option_unknown
# ============================================================


@pytest.mark.asyncio
async def test_option_intent_error_routes_to_option_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """option.intent LLM 异常 → 路由到 option_unknown。"""
    _patch_llm_to_raise(
        monkeypatch, option_intent_module, RuntimeError("Qwen timeout"),
        factory_name="get_qwen_structured",
    )

    graph = build_option_graph()
    final = await graph.ainvoke(_base_state("期权询价"))

    nodes = _trace_nodes(final)
    assert "option_intent" in nodes, nodes
    assert "option_unknown" in nodes, nodes
    assert "option_extract_inquiry" not in nodes
    assert "option_extract_place_or_modify" not in nodes

    err = final.get("error")
    assert err is not None
    assert err.node == "option_intent"
    assert err.type == "RuntimeError"


# ============================================================
# 子图层：close.intent 抛错 → close_unknown
# ============================================================


@pytest.mark.asyncio
async def test_close_intent_error_routes_to_close_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close.intent LLM 异常 → 路由到 close_unknown。"""
    _patch_llm_to_raise(
        monkeypatch, close_intent_module, ConnectionError("upstream down")
    )

    graph = build_close_graph()
    final = await graph.ainvoke(_base_state("平仓 H-202..."))

    nodes = _trace_nodes(final)
    assert "close_intent" in nodes, nodes
    assert "close_unknown" in nodes, nodes
    assert "close_place_close" not in nodes
    assert "close_holding_query" not in nodes

    err = final.get("error")
    assert err is not None
    assert err.node == "close_intent"
    assert err.type == "ConnectionError"


# ============================================================
# 主图层：intent_route 抛错 → fallback（不进任一子图）
# ============================================================


@pytest.mark.asyncio
async def test_main_graph_intent_route_error_routes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主图 intent_route LLM 失败 → cascade → fallback → render 仍出回复。

    关键路径：
    - ingest 正常
    - intent_route 第三层 LLM 抛错 → @safe_node 写 error → 跳 fallback
    - 不进 swap/option/option_close 任一子图
    - persist + render 仍执行
    """
    from app.nodes import intent_route as ir_module

    _patch_llm_to_raise(
        monkeypatch, ir_module, RuntimeError("intent llm dead"),
        factory_name="get_qwen_thinking",
    )

    graph = build_main_graph()
    final = await graph.ainvoke(
        {**_base_state("看不懂的随机消息内容"), "intent": None}
    )

    nodes = _trace_nodes(final)
    assert "ingest" in nodes
    assert "intent_route" in nodes
    assert "fallback" in nodes
    assert "render" in nodes
    # 没进入任一子图首节点
    assert "swap_intent" not in nodes
    assert "option_intent" not in nodes
    assert "close_intent" not in nodes

    err = final.get("error")
    assert err is not None
    assert err.node == "intent_route"


# ============================================================
# 主图层 + 子图层：进入 swap 子图后 intent 抛错 → swap_unknown → 仍走 persist/render
# ============================================================


@pytest.mark.asyncio
async def test_main_graph_swap_intent_error_full_cascade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端 cascade：

    ingest → intent_route(规则命中 swap) → swap 子图 → swap_intent 抛错
    → swap_unknown(子图层防御) → persist → render

    验证：
    1. swap_intent 抛错没让主图崩
    2. swap_unknown 兜底替代 swap_place_order/confirm/...
    3. persist + render 仍按主图边正常走完
    """
    _patch_llm_to_raise(
        monkeypatch, swap_intent_module, ValueError("structured parse fail")
    )

    graph = build_main_graph()
    # raw_text 含"互换"关键词，intent_route 第二层规则会命中 swap
    final = await graph.ainvoke(_base_state("互换 测试消息"))

    nodes = _trace_nodes(final)
    assert "ingest" in nodes
    assert "intent_route" in nodes
    assert "swap_intent" in nodes
    assert "swap_unknown" in nodes
    # 子图层兜底成功后，主图 fallback 不应被触发（错误已被子图消化）
    assert "swap_place_order" not in nodes
    assert "swap_confirm" not in nodes
    # 主图仍要走完 persist + render
    assert "persist" in nodes
    assert "render" in nodes

    err = final.get("error")
    assert err is not None
    assert err.node == "swap_intent"


# ============================================================
# 健壮性：多个节点都不会一齐抛错（验证 safe_node 隔离）
# ============================================================


@pytest.mark.asyncio
async def test_swap_unknown_does_not_re_raise_on_error_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error 已写入时 swap_unknown 仍正常返回（不二次抛错）。"""
    _patch_llm_to_raise(
        monkeypatch, swap_intent_module, ValueError("first failure")
    )

    graph = build_swap_graph()
    final = await graph.ainvoke(_base_state())

    # error 仍是首个失败节点（swap_unknown 没覆盖也没二次抛）
    err = final.get("error")
    assert err is not None
    assert err.node == "swap_intent"
    assert "swap_unknown" in _trace_nodes(final)
