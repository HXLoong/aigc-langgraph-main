"""SDK 实验任务只经 HTTP 执行，保留会话身份和失败轮次。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.langfuse import langfuse_eval as ev


def item():
    """平台首轮及子轮分离保存输入和期望。"""
    return SimpleNamespace(id="platform-id", metadata={"case_id": "case-http"},
        input={"send_text": "第一轮", "sub_scenes": [{"send_text": "第二轮", "quote_previous": True}]},
        expected_output={"response_contains": "ok", "sub_scenes": [{"response_contains": "ok"}]})


@pytest.mark.parametrize("error,code", [(None, 0), ({"node": "parse_instruction", "type": "ValueError", "message": "bad"}, None), (None, 400)])
async def test_pipeline_http_identity_and_failure_denominator(monkeypatch, error, code):
    """业务失败立即停止依赖轮，剩余轮不能从 PASS 分母消失。"""
    settings = ev.get_settings().model_copy(update={"eval_user_id": "test-user", "eval_room_id": "test-room"})
    monkeypatch.setattr(ev, "get_settings", lambda: settings)
    calls = []

    def response(request):
        """替换应用 HTTP 出口，任务进程不得直接构建图。"""
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/v1/workflows/run"
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {
            "reply_text": "ok", "api_code": code, "error": error,
        }}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        output = await ev.run_langgraph_pipeline(item=item(), client=client)
    if error or code:
        assert len(calls) == 1 and output["failure"]
        assert not output["passed"]
    else:
        assert len(calls) == 2 and output["passed"]
        assert calls[0]["conversation_id"] == calls[1]["conversation_id"]
        assert calls[1]["inputs"]["quote_content"] == "ok"
    assert output["case_id"] == "case-http"
