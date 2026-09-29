"""唯一模型失败后主图完成兜底、历史和审计，零重试、零业务提交。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.extraction.fields import EvidenceError
from app.graph.main import build_main_graph


@pytest.mark.parametrize("error", [ValueError("invalid structure"), EvidenceError("invalid source"), TimeoutError("model timeout")])
async def test_joint_model_failure_cascades_once_without_java(monkeypatch, error):
    """替换外部模型与 Java 出口，整条图仍按真实路由执行。"""
    invoke = AsyncMock(side_effect=error)
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", lambda: SimpleNamespace(
        with_structured_output=lambda _: SimpleNamespace(ainvoke=invoke)))
    backend = AsyncMock()
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    monkeypatch.setattr("app.tools.swap_client.SwapClientHttpx.operate", backend)
    audit = AsyncMock()
    monkeypatch.setattr("app.nodes.persist.write_node_trace", audit)
    state = await build_main_graph().ainvoke({"raw_text": "期权询价", "conversation_id": "c",
        "message_id": 1, "user_id": "u", "room_id": "r"})
    assert state["error"].node == "parse_instruction"
    assert state["reply_text"]
    names = [entry.node for entry in state["trace"]]
    assert "fallback" in names and names[-1] == "persist"
    assert "option_intent" not in names
    assert len(state["history_messages"]) == 2
    assert invoke.await_count == 1
    backend.assert_not_called()
    audit.assert_awaited_once()
