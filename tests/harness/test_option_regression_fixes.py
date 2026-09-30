"""快速入口、传输数值与固定时间前置条件的最小复现。"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from harness.differ import check_structured_assertions
from harness.golden import dataset_input, normalize_case
from harness.multi_turn import run_case_multi


def inquiry_case(**extra):
    """合成用例不依赖真实业务身份，也不携带预期给服务端。"""
    return normalize_case({"caseNo": "synthetic", "category": "option", "send_text": "询价",
                           "at_bot": False, "fast_query": "1",
                           "expected": {"intent": "new_inquiry"}, **extra}, origin="synthetic:1")


async def test_fast_flag_survives_loading_projection_and_http():
    """字段不能只留在 JSONL，必须实际送到工作流 HTTP 入口。"""
    case = inquiry_case()
    assert case.turns[0].model_dump().get("fast_query") == "1"
    assert dataset_input(case)["fast_query"] == "1"
    requests = []

    def reply(request):
        """记录真实 HTTP 请求体，返回最小合成回执。"""
        requests.append(json.loads(request.content)["inputs"])
        return httpx.Response(200, json={"data": {"status": "succeeded", "outputs": {
            "product_type": "option", "intent": "new_inquiry", "reply_text": "询价结果"}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r", client=client)
    assert result.failure is None
    assert requests[0]["fast_query"] == "1" and requests[0]["at_bot"] is False


async def test_fast_intent_checks_entry_node_without_business_or_model_calls():
    """快速样例在意图套件中验入口规则，不冒充普通 LLM 意图测试。"""
    from harness.intent_runner import run_frozen_case

    requests = []

    def reply(request):
        """节点 HTTP 返回固定入口结果；其它节点请求会使断言失败。"""
        body = json.loads(request.content)
        requests.append(body)
        assert body["node"] == "entry_route"
        assert body["state"]["fast_query"] == "1"
        return httpx.Response(200, json={"output": {
            "entry_branch": "quick_inquiry", "product_type": "option", "intent": "new_inquiry"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        result = await run_frozen_case(inquiry_case(), base_url="http://test", user_id="u", client=client)
    assert result.failure is None and len(requests) == 1
    assert result.turns[0].outputs["entry_branch"] == "quick_inquiry"


@pytest.mark.parametrize("field,actual,expected", [
    ("strikePercentage", "80", 80), ("limitPrice", "10.00", 10),
    ("povRatio", "11", 11), ("notionalAmount", "2500000", 2500000),
    ("strikePercentage", "80%", 80), ("limitPrice", "0.100000000000000001", "0.100000000000000001"),
])
def test_declared_decimal_fields_compare_numeric_value(field, actual, expected):
    """Java 接受的十进制数字字符串按值比较，不改变实际提交数据。"""
    output = {"product_type": "option", "place_params": {"orderList": [{field: actual}]}}
    assert check_structured_assertions(output, {"place_params": {"orderList": [{field: expected}]}}) == []
    assert output["place_params"]["orderList"][0][field] == actual


@pytest.mark.parametrize("product,field,actual,expected", [
    ("option", "limitPrice", True, 1), ("option", "limitPrice", "100万", 1000000),
    ("option", "limitPrice", "NaN", 10), ("option", "limitPrice", "10.001", 10),
    ("option", "limitPrice", "80%", 80), ("option", "limitPrice", "Infinity", 10),
    ("option", "stockCode", "000001", 1), ("option", "orderId", "001", 1),
    ("swap", "placeOrderQuantity", "10", 10), ("swap", "placeOrderQuantity", 10.0, 10),
    ("option", "hasFastExecutionIntent", 1, True),
])
def test_numeric_comparison_preserves_contract_boundaries(product, field, actual, expected):
    """类型、身份、单位、精度错误仍然失败，整数不得因值相等而放宽传输类型。"""
    output = {"product_type": product, "place_params": {"orderList": [{field: actual}]}}
    assert check_structured_assertions(output, {"place_params": {"orderList": [{field: expected}]}})


async def test_expired_case_fails_before_message_preparation_or_http(monkeypatch):
    """固定时间过期时保留完整失败分母，不发出任何交易请求。"""
    from harness import scenario_inputs

    class Clock(datetime):
        """固定本地时间，测试不依赖执行机器当前时钟。"""
        @classmethod
        def now(cls, tz=None):
            """返回确定的过期时刻，不依赖运行机器的时区。"""
            return datetime(2026, 9, 29, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    monkeypatch.setattr(scenario_inputs, "datetime", Clock, raising=False)
    case = inquiry_case(execution_before="14:30")
    prepare = AsyncMock()

    def forbidden(request):
        """若前置检查失效，直接暴露不应发生的 HTTP 调用。"""
        pytest.fail("expired case issued HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        result = await run_case_multi(case, base_url="http://test", user_id="u", room_id="r",
                                     client=client, before_turn=prepare)
    assert result.failure["kind"] == "fixture_precondition"
    assert result.remaining_turns == 1 and not result.turns
    prepare.assert_not_awaited()


@pytest.mark.parametrize("body,expected_status", [
    ({"optionRfq": {"strike": ["80"]}}, "present"),
    ({"type": "new_inquiry"}, "pending_business_acceptance"),
])
def test_quick_request_parameter_coverage_uses_actual_assertions(body, expected_status):
    """迁移到快速出站参数的标注不能丢失覆盖统计，仅有动作标签则仍缺参数。"""
    from harness.evaluation import parameter_coverage

    case = inquiry_case(expected={"intent": "new_inquiry", "backend_request": body})
    assert parameter_coverage(case)["status"] == expected_status
