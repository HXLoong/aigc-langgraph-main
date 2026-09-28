"""ADR 0026：同一消息的每次合法调用都独立执行并返回本次结果。"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI

from app.api.routes import router
from app.graph.state import ErrorInfo


class CountingGraph:
    """模拟图的可观察结果，不访问后端或模型。"""

    def __init__(self, fail_first: bool = False) -> None:
        """记录调用次数及第一轮是否失败。"""
        self.calls = 0
        self.fail_first = fail_first

    async def ainvoke(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """每次调用生成不同回执，帮助识别旧响应回放。"""
        self.calls += 1
        if self.fail_first and self.calls == 1:
            return {**state, "error": ErrorInfo(node="persist_intent", type="SetIntentError", message="synthetic")}
        return {**state, "reply_text": f"call-{self.calls}", "intent": "confirm_order",
                "product_type": "option", "api_code": 900, "api_result": "真实本次回执"}


class ForbiddenStore:
    """入口不得再访问消息级占位与回放存储。"""

    async def begin(self, *args: Any, **kwargs: Any) -> None:
        """任何占位尝试都代表仍有旧职责。"""
        raise AssertionError("LangGraph 不负责消息占位")


async def _call_twice(fail_first: bool = False) -> tuple[CountingGraph, list[httpx.Response]]:
    """在同一应用上发送同一个 messageId 两次。"""
    app = FastAPI()
    app.include_router(router)
    graph = CountingGraph(fail_first)
    app.state.main_graph = graph
    app.state.idempotency_store = ForbiddenStore()
    body = {"user": "user", "conversation_id": "conversation", "inputs": {
        "messageId": 123, "rawContent": "确认下单", "roomId": "room", "userId": "user",
        "retry_origin": "system", "retry_attempt": "2",
    }}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        replies = [await client.post("/v1/workflows/run", json=body) for _ in range(2)]
    return graph, replies


async def test_repeated_message_executes_each_call_without_notification_projection() -> None:
    """同消息分别执行；重投标记不静默本次业务回复。"""
    graph, replies = await _call_twice()
    assert [response.status_code for response in replies] == [200, 200]
    bodies = [response.json() for response in replies]
    assert graph.calls == 2 and [body["answer"] for body in bodies] == ["call-1", "call-2"]
    assert bodies[0]["data"]["outputs"]["trace_id"] != bodies[1]["data"]["outputs"]["trace_id"]
    assert all("replayed" not in body["data"]["outputs"] for body in bodies)
    assert all("idempotency_status" not in body["data"]["outputs"] for body in bodies)


async def test_failed_call_does_not_seal_later_success() -> None:
    """首轮写回失败后，新调用可重新执行，不回放旧 502。"""
    graph, replies = await _call_twice(fail_first=True)
    assert [response.status_code for response in replies] == [502, 200]
    assert graph.calls == 2 and replies[1].json()["answer"] == "call-2"
