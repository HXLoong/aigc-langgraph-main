"""cascade 防御专项测试：close.intent 节点异常 → @safe_node → 子图路由到 close_unknown。

Issue #32 要求的 3 个用例：
  1. LLM 抛 ValueError → state['error'] 写入
  2. LLM 返回 ValidationError（Pydantic 拒绝）→ state['error'] 写入
  3. 子图集成：intent 抛错 → 路由走 close_unknown 兜底
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.close import build_close_graph
from app.subgraphs.close import intent as intent_module
from app.subgraphs.close.intent import close_intent
from app.subgraphs.close.models import CloseIntentOutput

_BASE_STATE = {
    "raw_text": "帮我平仓",
    "conversation_id": "test-cascade-close",
    "user_id": "u1",
    "room_id": "r1",
    "message_id": 1,
    "message_content": "帮我平仓",
}


def _patch_llm_error(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=exc))
    )
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_llm)


@pytest.mark.asyncio
async def test_close_intent_llm_value_error_writes_error_to_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 抛 ValueError → @safe_node 捕获 → state['error'] 写入，图不崩。"""
    _patch_llm_error(monkeypatch, ValueError("平仓意图解析失败"))

    result = await close_intent({"raw_text": "帮我平仓"})

    assert result.get("error") is not None
    err = result["error"]
    assert err.node == "close_intent"
    assert err.type == "ValueError"
    assert "平仓意图解析失败" in err.message
    assert any(
        e.node == "close_intent" and e.decision == "error"
        for e in result.get("trace", [])
    )


@pytest.mark.asyncio
async def test_close_intent_pydantic_validation_error_writes_error_to_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 返回无效 type 字段 → ValidationError → @safe_node 捕获 → state['error']。"""

    def _raise(*_args, **_kwargs) -> None:
        CloseIntentOutput(type="invalid_close_intent_type", confidence=0.91, evidence=[{"text": "本轮意图模型测试输入", "origin": "raw"}])  # type: ignore[arg-type]

    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=_raise))
    )
    monkeypatch.setattr(intent_module, "get_qwen_thinking", lambda: fake_llm)

    from app.config import get_settings
    settings = get_settings().model_copy(update={
        "node_retry_max_attempts": 2, "node_retry_initial_interval_seconds": .001,
    })
    monkeypatch.setattr("app.graph.retry.get_settings", lambda: settings)
    result = await build_close_graph().ainvoke(_BASE_STATE)
    assert fake_llm.with_structured_output.return_value.ainvoke.await_count == 2

    assert result.get("error") is not None
    err = result["error"]
    assert err.node == "close_intent"
    assert "ValidationError" in err.type
    assert result.get("trace")



@pytest.mark.asyncio
async def test_close_subgraph_intent_error_routes_to_close_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close.intent 抛 RuntimeError → state['error'] → 子图路由到 close_unknown 兜底。"""
    _patch_llm_error(monkeypatch, RuntimeError("LLM 服务不可用"))

    graph = build_close_graph()
    final = await graph.ainvoke(_BASE_STATE)

    assert final.get("error") is not None
    assert final["error"].node == "close_intent"

    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "close_intent" in trace_nodes
    assert "close_unknown" in trace_nodes
    for unexpected in (
        "close_holding_query",
        "close_place_close",
        "close_confirm_close",
        "close_cancel_close",
        "close_confirm_cancel",
        "close_query_status",
    ):
        assert unexpected not in trace_nodes
