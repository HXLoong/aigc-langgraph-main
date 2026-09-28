"""经同一 HTTP runner 注入当前测试上下文，并解析跨轮真实单号。"""
import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.langfuse import langfuse_eval as ev


@pytest.mark.parametrize("reply,count", [
    ("单号：Q-20260923-0000000001", 2),
    ("单号：Q-20260923-0000000001\n单号：Q-20260923-0000000002", 1),
])
async def test_previous_reference_comes_from_real_http_reply(monkeypatch, reply, count):
    """缺少唯一订单时不猜最近单，也不继续依赖轮。"""
    settings = ev.get_settings().model_copy(update={"eval_user_id": "test-user", "eval_room_id": "test-room"})
    monkeypatch.setattr(ev, "get_settings", lambda: settings)
    requests = []

    def response(request):
        """记录唯一 HTTP 入口的实际输入。"""
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {"reply_text": reply}}})

    item = SimpleNamespace(id="reference", input={"send_text": "查询", "sub_scenes": [
        {"send_text": "查询 {{previous_order_id}} 状态", "quote_previous": True}]},
        expected_output={"response_contains": "单号", "sub_scenes": [{"response_contains": "单号"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await ev.run_langgraph_pipeline(item=item, client=client)
    assert len(requests) == count
    if count == 2:
        assert requests[1]["inputs"]["raw_text"] == "查询 Q-20260923-0000000001 状态"
        assert result["passed"]
    else:
        assert not result["passed"] and result["failure"]["turn"] == 2
