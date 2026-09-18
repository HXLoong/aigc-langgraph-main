"""cascade 防御专项测试：option.intent 节点异常 → @safe_node → 子图路由到 option_unknown。

Issue #32 要求的 3 个用例：
  1. LLM 抛 ValueError → state['error'] 写入
  2. LLM 返回 ValidationError（Pydantic 拒绝）→ state['error'] 写入
  3. 子图集成：intent 抛错 → 路由走 option_unknown 兜底
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.subgraphs.option import build_option_graph
from app.subgraphs.option import intent as intent_module
from app.subgraphs.option.intent import option_intent
from app.subgraphs.option.models import OptionIntentOutput

_BASE_STATE = {
    "raw_text": "我想询价一个期权",
    "conversation_id": "test-cascade-option",
    "user_id": "u1",
    "room_id": "r1",
    "message_id": 1,
    "message_content": "我想询价一个期权",
}


def _patch_llm_error(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=exc))
    )
    monkeypatch.setattr(intent_module, "get_qwen_structured", lambda: fake_llm)


@pytest.mark.asyncio
async def test_option_intent_llm_value_error_writes_error_to_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 抛 ValueError → @safe_node 捕获 → state['error'] 写入，图不崩。"""
    _patch_llm_error(monkeypatch, ValueError("期权意图解析失败"))

    result = await option_intent({"raw_text": "我想询价一个期权"})

    assert result.get("error") is not None
    err = result["error"]
    assert err.node == "option_intent"
    assert err.type == "ValueError"
    assert "期权意图解析失败" in err.message
    assert any(
        e.node == "option_intent" and e.decision == "error"
        for e in result.get("trace", [])
    )


@pytest.mark.asyncio
async def test_option_intent_pydantic_validation_error_writes_error_to_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 返回无效 type 字段 → ValidationError → @safe_node 捕获 → state['error']。"""

    def _raise(*_args, **_kwargs) -> None:
        OptionIntentOutput(type="not_a_valid_option_intent")  # type: ignore[arg-type]

    fake_llm = MagicMock()
    fake_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(side_effect=_raise))
    )
    monkeypatch.setattr(intent_module, "get_qwen_structured", lambda: fake_llm)

    from app.config import get_settings
    settings = get_settings().model_copy(update={
        "node_retry_max_attempts": 2, "node_retry_initial_interval_seconds": .001,
    })
    monkeypatch.setattr("app.graph.retry.get_settings", lambda: settings)
    result = await build_option_graph().ainvoke(_BASE_STATE)
    assert fake_llm.with_structured_output.return_value.ainvoke.await_count == 2

    assert result.get("error") is not None
    err = result["error"]
    assert err.node == "option_intent"
    assert "ValidationError" in err.type
    assert result.get("trace")



@pytest.mark.asyncio
async def test_option_subgraph_intent_error_routes_to_option_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """option.intent 抛 RuntimeError → state['error'] → 子图路由到 option_unknown 兜底。"""
    _patch_llm_error(monkeypatch, RuntimeError("LLM 服务不可用"))

    graph = build_option_graph()
    final = await graph.ainvoke(_BASE_STATE)

    assert final.get("error") is not None
    assert final["error"].node == "option_intent"

    trace_nodes = [e.node for e in final.get("trace", [])]
    assert "option_intent" in trace_nodes
    assert "option_unknown" in trace_nodes
    for unexpected in (
        "option_extract_inquiry",
        "option_extract_place",
        "option_extract_confirm_place",
        "option_extract_cancel_place",
        "option_extract_cancel",
        "option_extract_confirm_cancel",
        "option_extract_query",
    ):
        assert unexpected not in trace_nodes
