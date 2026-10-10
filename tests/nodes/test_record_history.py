from __future__ import annotations

import pytest

from app.graph.state import Message
from app.nodes.record_history import record_history


@pytest.mark.asyncio
async def test_record_history_appends_current_user_and_assistant_messages() -> None:
    update = await record_history(
        {
            "raw_text": "100万",
            "reply_text": "已补充名义本金100万元。",
        }
    )

    assert update["history_messages"] == [
        Message(role="user", content="100万"),
        Message(role="assistant", content="已补充名义本金100万元。"),
    ]
    # @safe_node 自动补一条 TraceEntry（ADR 0024 阶段 0 起 record_history 受保护）
    assert [entry.node for entry in update["trace"]] == ["record_history"]


def test_record_history_is_wrapped_by_safe_node() -> None:
    """ADR 0024 阶段 0：record_history 曾是全图唯一未受 @safe_node 保护的节点，
    异常会打穿整图；必须与其它节点一样降级到 state['error']。"""
    assert hasattr(record_history, "__wrapped__"), "record_history 必须用 @safe_node 装饰"


@pytest.mark.asyncio
async def test_record_history_exception_degrades_to_error_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.nodes.record_history as mod

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("history broken")

    monkeypatch.setattr(mod, "Message", _boom)
    update = await record_history({"raw_text": "x", "reply_text": "y"})
    assert update["error"].node == "record_history"
    assert "history_messages" not in update
