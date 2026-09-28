"""业务与意图评测必须执行服务端入口，并使用真实返回值评分。"""
from __future__ import annotations

import importlib
import importlib.util
import json

import httpx

from harness.golden import GoldenCase


def _module():
    """统一 HTTP 评测入口缺失时先给出 RED。"""
    assert importlib.util.find_spec("harness.http_evaluation") is not None, "缺少统一 HTTP 评测入口"
    return importlib.import_module("harness.http_evaluation")


async def test_business_evaluation_uses_http_and_all_field_assertions() -> None:
    """有回复但参数错误时失败，不能退化为 reply-check。"""
    module = _module()
    case = GoldenCase(id="field-diff", category="option", turns=[{
        "send_text": "期权询价", "expected": {"place_params": {"orderList": [{"notionalAmount": "1000000"}]}}
    }])
    paths = []

    def response(request):
        """模拟应用 HTTP 回执，字段值故意与期望不同。"""
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {
            "reply_text": "有回复", "place_params": {"orderList": [{"notionalAmount": "2000000"}]},
        }}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await module.run_case(case, suite="business", base_url="http://test", user_id="u", room_id="r", client=client)
    assert paths == ["/v1/workflows/run"]
    assert not result["passed"] and result["evaluations"][0]["value"] == 0
    assert "notionalAmount" in str(result["turns"][0]["diff"])


async def test_frozen_intent_uses_node_http_without_business_submission() -> None:
    """冻结样本不恢复 checkpoint，不执行交易节点，也不把 expected 放进输入。"""
    module = _module()
    case = GoldenCase(id="intent-frozen", category="intent/option", turns=[{
        "send_text": "期权询价", "quote_previous": False,
        "expected": {"product_type": "option", "intent": "new_inquiry"},
    }])
    requests = []

    def response(request):
        """模拟唯一联合解析节点的真实 HTTP 输出形状。"""
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        return httpx.Response(200, json={"output": {
            "product_type": "option", "intent": "new_inquiry",
            "parsed_instruction": {"product_type": "option", "intent": "new_inquiry", "orders": []},
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await module.run_case(case, suite="intent", base_url="http://test", user_id="u", room_id="r", client=client)
    assert len(requests) == 1 and requests[0][0] == "/v1/nodes/run"
    assert requests[0][1]["node"] == "parse_instruction"
    assert "expected" not in requests[0][1]["state"]
    assert result["passed"] and result["evaluations"][0]["name"] == "det_intent_match_pass"
