from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts import langfuse_eval


class _FailingFirstTurnGraph:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, state: dict, config: dict) -> dict:
        self.calls += 1
        return {
            **state,
            "product_type": "option",
            "intent": "new_inquiry",
            "reply_text": "系统暂时不可用，请稍后重试。",
            "api_code": None,
            "error": {
                "node": "option_extract_inquiry",
                "type": "BackendUnreachableError",
                "message": "ticker: timeout",
            },
        }


class _BackendCodeFailingGraph(_FailingFirstTurnGraph):
    async def ainvoke(self, state: dict, config: dict) -> dict:
        self.calls += 1
        return {
            **state,
            "product_type": "option",
            "intent": "new_inquiry",
            "reply_text": "询价提交失败。",
            "api_code": 50301,
            "error": None,
        }


class _RecordingGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def ainvoke(self, state: dict, config: dict) -> dict:
        self.calls.append(
            (state["conversation_id"], config["configurable"]["thread_id"])
        )
        return {
            **state,
            "product_type": "option",
            "intent": "new_inquiry",
            "reply_text": "ok",
            "api_code": 0,
            "error": None,
        }


@pytest.mark.asyncio
async def test_pipeline_uses_one_uuid_conversation_id_for_all_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _RecordingGraph()
    monkeypatch.setattr(langfuse_eval, "build_main_graph", lambda _cp: graph)
    monkeypatch.setattr(langfuse_eval, "_TURN_INTERVAL_SECONDS", 0)
    item = SimpleNamespace(
        id="case-001",
        input={
            "turns": [
                {"raw_content": "贵州茅台欧式看涨，1M"},
                {"raw_content": "100万"},
            ]
        },
    )

    await langfuse_eval.run_langgraph_pipeline(item=item)

    assert len(graph.calls) == 2
    conversation_ids = {conversation_id for conversation_id, _ in graph.calls}
    thread_ids = {thread_id for _, thread_id in graph.calls}
    assert conversation_ids == thread_ids
    assert len(conversation_ids) == 1
    conversation_id = conversation_ids.pop()
    assert str(UUID(conversation_id)) == conversation_id
    assert conversation_id != "eval-case-001"


@pytest.mark.asyncio
async def test_pipeline_stops_after_first_structured_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _FailingFirstTurnGraph()
    monkeypatch.setattr(langfuse_eval, "build_main_graph", lambda _cp: graph)
    monkeypatch.setattr(langfuse_eval, "_TURN_INTERVAL_SECONDS", 0)
    item = SimpleNamespace(
        id="case-fail-fast",
        input={
            "turns": [
                {"raw_content": "贵州茅台欧式看涨，1M"},
                {"raw_content": "100万", "quote_desc": "引用上一轮"},
            ]
        },
    )

    output = await langfuse_eval.run_langgraph_pipeline(item=item)

    assert graph.calls == 1
    assert len(output["turns"]) == 1
    assert output["failure"] == {
        "turn": 1,
        "kind": "node_error",
        "api_code": None,
        "error": {
            "node": "option_extract_inquiry",
            "type": "BackendUnreachableError",
            "message": "ticker: timeout",
        },
        "reply_text": "系统暂时不可用，请稍后重试。",
    }
    assert output["remaining_turns"] == 1


@pytest.mark.asyncio
async def test_pipeline_stops_after_first_nonzero_api_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _BackendCodeFailingGraph()
    monkeypatch.setattr(langfuse_eval, "build_main_graph", lambda _cp: graph)
    monkeypatch.setattr(langfuse_eval, "_TURN_INTERVAL_SECONDS", 0)
    item = SimpleNamespace(
        id="case-api-fail-fast",
        input={
            "turns": [
                {"raw_content": "贵州茅台欧式看涨，1M，100万"},
                {"raw_content": "确认", "quote_desc": "引用上一轮"},
            ]
        },
    )

    output = await langfuse_eval.run_langgraph_pipeline(item=item)

    assert graph.calls == 1
    assert output["failure"]["kind"] == "backend_error"
    assert output["failure"]["api_code"] == 50301
    assert output["remaining_turns"] == 1
