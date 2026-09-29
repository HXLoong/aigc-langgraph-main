"""在 HTTP 派发边界验证一次工具调用的模型额度。"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, Field

from app.llm import clients


class Answer(BaseModel):
    """结构化模型的最小可观察输出。"""

    answer: str = Field(description="合成测试回复")


def _budget_module() -> Any:
    """缺少额度模块时以明确断言失败，避免把导入错误当成 RED。"""
    assert importlib.util.find_spec("app.llm.budget") is not None, "缺少调用级模型额度守卫"
    return importlib.import_module("app.llm.budget")


async def test_parallel_and_nested_invocations_share_one_physical_request(monkeypatch) -> None:
    """并行任务和嵌套作用域共享额度；下一次独立调用重新计数。"""
    budget = _budget_module()
    dispatched: list[httpx.Request] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        """仅模拟模型 HTTP 响应，使用真实结构化解析及 SDK。"""
        dispatched.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json={"id": "synthetic", "object": "chat.completion",
            "created": 0, "model": "deepseek-v4-pro", "choices": [{"index": 0,
                "finish_reason": "tool_calls", "message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "call-1", "type": "function", "function": {
                        "name": "Answer", "arguments": '{"answer":"ok"}',
                    }}]}}]})

    monkeypatch.setattr(clients, "DefaultAsyncHttpxClient", lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kw,
    ))
    model = clients._build_llm("deepseek-v4-pro")
    chain = model.with_structured_output(Answer)
    try:
        with budget.model_request_scope() as first:
            with budget.model_request_scope():
                outcomes = await asyncio.gather(chain.ainvoke("one"), chain.ainvoke("two"), return_exceptions=True)
            assert len(dispatched) == first.requests == 1
            assert sum(isinstance(item, Answer) for item in outcomes) == 1
            assert sum(isinstance(item, Exception) for item in outcomes) == 1
        with budget.model_request_scope() as second:
            assert (await chain.ainvoke("next call")).answer == "ok"
            assert second.requests == 1 and len(dispatched) == 2
    finally:
        await model.http_async_client.aclose()
        model.http_client.close()


async def test_failed_dispatch_also_consumes_request_budget(monkeypatch) -> None:
    """网络失败不得返还额度，也不得由 SDK 自动重试。"""
    budget = _budget_module()
    dispatched = []

    def respond(request: httpx.Request) -> httpx.Response:
        """记录真实派发次数后模拟连接中断。"""
        dispatched.append(request)
        raise httpx.ConnectError("synthetic failure", request=request)

    monkeypatch.setattr(clients, "DefaultAsyncHttpxClient", lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kw,
    ))
    model = clients._build_llm("deepseek-v4-pro")
    try:
        with budget.model_request_scope() as scope:
            for _ in range(2):
                with pytest.raises(openai.APIConnectionError):
                    await model.ainvoke("synthetic")
            assert len(dispatched) == scope.requests == 1
    finally:
        await model.http_async_client.aclose()
        model.http_client.close()


async def test_token_limit_stops_even_when_partial_output_is_valid_json(monkeypatch) -> None:
    """finish_reason=length 时不能把可解析的半批订单当完整结果提交。"""
    import json
    from unittest.mock import AsyncMock

    from app.graph.main import build_main_graph
    from tests.joint_support import instruction_data

    dispatched = []
    raw = "期权询价茅台"
    payload = instruction_data("option", "new_inquiry", raw, orders=[{"stockCode": "茅台"}])

    def response(request):
        """返回合法 JSON 但明确标记输出截断，验证真实 SDK 到主图边界。"""
        dispatched.append(request)
        return httpx.Response(200, json={"id": "partial", "object": "chat.completion", "created": 0,
            "model": "deepseek-v4-pro", "choices": [{"index": 0, "finish_reason": "length",
                "message": {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1",
                    "type": "function", "function": {"name": "OptionInstruction", "arguments": json.dumps(payload)}}]}}]})

    monkeypatch.setattr(clients, "DefaultAsyncHttpxClient", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(response), **kw))
    model = clients._build_llm("deepseek-v4-pro")
    monkeypatch.setattr("app.nodes.parse_instruction.get_llm_standard", lambda: model)
    backend = AsyncMock(return_value={"code": 0, "data": "must not submit partial"})
    monkeypatch.setattr("app.tools.option_client.OptionClientHttpx.operate", backend)
    monkeypatch.setattr("app.nodes.persist.write_node_trace", AsyncMock())
    try:
        with _budget_module().model_request_scope():
            result = await build_main_graph().ainvoke({"raw_text": raw, "conversation_id": "c",
                "message_id": 1, "room_id": "r", "user_id": "u"})
        assert len(dispatched) == 1
        backend.assert_not_called()
        assert result["error"].code == "E2" and "容量" in result["reply_text"]
    finally:
        await model.http_async_client.aclose()
        model.http_client.close()
