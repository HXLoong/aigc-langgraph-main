"""close 子图路由测试 · intent → conditional → holding_query / todo。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import holding_query as hq_module
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.models import CloseIntentOutput, HoldingQueryParams
from app.tools.models import CommonResult


def _patch_close_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """close/backend.py 调用的 OptionClientHttpx.operate 不打真网络（路由测试关注
    路由本身，不关注真后端联调，真联调见 scripts/probe_close_write_e2e.py）。"""

    async def _fake_operate(self, req):  # type: ignore[no-untyped-def]
        return CommonResult(code=0, msg="ok", data="mock-backend-result")

    monkeypatch.setattr(
        "app.tools.option_client.OptionClientHttpx.operate", _fake_operate
    )


def _patch_intent(monkeypatch: pytest.MonkeyPatch, intent_type: str) -> None:
    fake_output = CloseIntentOutput(type=intent_type)  # type: ignore[arg-type]
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=fake_output)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_base)


def _patch_holding_query(monkeypatch: pytest.MonkeyPatch, params: HoldingQueryParams) -> None:
    fake_llm = MagicMock()
    fake_llm.ainvoke = AsyncMock(return_value=params)
    fake_base = MagicMock()
    fake_base.with_structured_output = MagicMock(return_value=fake_llm)
    monkeypatch.setattr(hq_module, "get_qwen_thinking", lambda: fake_base)
    monkeypatch.setattr(
        hq_module,
        "call_close_backend",
        AsyncMock(return_value={"api_code": 0, "api_result": "backend reply"}),
    )


@pytest.mark.asyncio
async def test_close_query_routes_to_holding_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_order_query → close_holding_query 节点。"""
    _patch_intent(monkeypatch, "close_order_query")
    _patch_holding_query(
        monkeypatch,
        HoldingQueryParams(closeable_only=False),
    )
    _patch_close_backend(monkeypatch)
    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "我有哪些期权持仓",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "我有哪些期权持仓",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_intent" in trace_nodes
    assert "close_holding_query" in trace_nodes
    assert "close_todo" not in trace_nodes
    assert final.get("intent") == "close_order_query"
    assert final.get("close_params") is not None
    assert final["close_params"]["closeable_only"] is False


@pytest.mark.asyncio
async def test_unknown_intent_routes_to_close_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """unknown_intent 走 close_unknown 兜底（close 子图 7/7 真节点全到位）。"""
    _patch_intent(monkeypatch, "unknown_intent")
    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "你好",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "你好",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_unknown" in trace_nodes
    assert "close_holding_query" not in trace_nodes
    assert "close_place_close" not in trace_nodes


@pytest.mark.asyncio
async def test_close_intent_error_routes_to_todo_not_holding_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """intent 节点 LLM 失败 → state['error'] → 走 todo（不进 holding_query）。"""
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("LLM down")))
    )
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_llm)
    graph = build_close_graph()
    final = await graph.ainvoke(
        {
            "raw_text": "x",
            "conversation_id": "t",
            "user_id": "u",
            "room_id": "r",
            "message_id": 1,
            "message_content": "x",
        }
    )
    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_holding_query" not in trace_nodes
    assert final.get("error") is not None
